# apps/worker/tasks/webhook_tasks.py
import os
import httpx
from celery import Celery
from pymongo import MongoClient
from datetime import datetime
import uuid
import sys

sys.path.insert(0, "/app")

# Import our new AI parser
from services.ai.extraction import extract_lead_parameters

redis_url = os.getenv("REDIS_URL", "redis://redis:6379/0")
celery_app = Celery("nph_tasks", broker=redis_url, backend=redis_url)

@celery_app.task(name="tasks.webhook_tasks.process_incoming_message_event")
def process_incoming_message_event(event_id: str):
    """The core pipeline: Event -> AI Extraction -> Lead Update -> Match Trigger."""
    
    mongo_url = os.getenv("MONGO_URL") or os.getenv("MONGO_URI")
    client = MongoClient(mongo_url)
    db = client["nph_core"]
    
    # 1. Fetch the raw payload
    event = db["webhook_events"].find_one({"event_id": event_id})
    if not event:
        return f"Failure: Event '{event_id}' not found."

    db["webhook_events"].update_one({"event_id": event_id}, {"$set": {"processing_status": "processing"}})

    try:
        sender_phone = event.get("sender")
        raw_text = event.get("payload", {}).get("text", "")

        if not raw_text:
            raise ValueError("No text payload found to process.")

        # 2. Execute Local AI Extraction
        print(f"[Worker] Sending text to Llama 3.2 for sender {sender_phone}...")
        extracted_data = extract_lead_parameters(raw_text)
        
        if not extracted_data:
            raise ValueError("AI failed to extract meaningful JSON.")

        # 3. Upsert Lead Profile using Phone Number as unique anchor
        lead = db["leads"].find_one({"phone": sender_phone})
        lead_id = lead["lead_id"] if lead else f"lead_{uuid.uuid4().hex[:8]}"

        lead_payload = {
            "lead_id": lead_id,
            "phone": sender_phone,
            "requirement_type": extracted_data.get("requirement_type", "rent"),
            "configuration": {"bhk": extracted_data.get("bhk", 0)},
            "preferred_areas": extracted_data.get("preferred_areas", []),
            "budget_min": 0,
            "budget_max": extracted_data.get("budget_max", 0),
            "parking": extracted_data.get("parking", False),
            "source": event.get("platform", "whatsapp"),
            "updated_at": datetime.utcnow()
        }

        # Update or create the lead record
        db["leads"].update_one(
            {"phone": sender_phone},
            {"$set": lead_payload, "$setOnInsert": {"created_at": datetime.utcnow(), "hotness_score": 0}},
            upsert=True
        )

        # 4. Trigger the Matching Engine via internal Docker network API call
        print(f"[Worker] Lead {lead_id} mapped. Triggering matching engine...")
        api_url = os.getenv("INTERNAL_API_URL", "http://api:8000")
        with httpx.Client(timeout=10.0) as http_client:
            http_client.post(f"{api_url}/matches/trigger/{lead_id}")

        # 5. Close out the event successfully
        db["webhook_events"].update_one(
            {"event_id": event_id},
            {"$set": {"processing_status": "completed", "processed_at": datetime.utcnow()}}
        )
        return f"Success: AI Processed & Matched Lead {lead_id}."
        
    except Exception as e:
        db["webhook_events"].update_one(
            {"event_id": event_id},
            {"$set": {"processing_status": "failed", "error_log": str(e)}}
        )
        return f"Error on '{event_id}': {str(e)}"