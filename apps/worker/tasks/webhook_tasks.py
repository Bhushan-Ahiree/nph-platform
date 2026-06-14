# apps/worker/tasks/webhook_tasks.py
import os
import httpx
from celery import Celery
from pymongo import MongoClient
from datetime import datetime, timezone
import uuid
import sys

sys.path.insert(0, "/app")

# Import our AI parser and the Commission Shield mask
from services.ai.extraction import extract_lead_parameters
from services.matching.engine import mask_property_for_client

redis_url = os.getenv("REDIS_URL", "redis://redis:6379/0")
celery_app = Celery("nph_tasks", broker=redis_url, backend=redis_url)

@celery_app.task(name="tasks.webhook_tasks.process_incoming_message_event")
def process_incoming_message_event(event_id: str):
    """The core pipeline: Event -> AI Extraction -> Lead Update -> API Search -> WhatsApp Reply."""
    
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
            "updated_at": datetime.now(timezone.utc)
        }

        # Update or create the lead record
        db["leads"].update_one(
            {"phone": sender_phone},
            {"$set": lead_payload, "$setOnInsert": {"created_at": datetime.now(timezone.utc), "hotness_score": 0}},
            upsert=True
        )

        # 4. Trigger the Search API internally!
        print(f"[Worker] Lead {lead_id} mapped. Searching inventory for matches...")
        api_url = os.getenv("INTERNAL_API_URL", "http://api:8000")
        
        search_params = {"limit": 3}
        if extracted_data.get("bhk"):
            search_params["bhk"] = extracted_data["bhk"]
        if extracted_data.get("budget_max"):
            search_params["max_price"] = extracted_data["budget_max"]
        if extracted_data.get("preferred_areas"):
            search_params["area"] = extracted_data["preferred_areas"][0]
            
        with httpx.Client(timeout=10.0) as http_client:
            response = http_client.get(f"{api_url}/properties/search", params=search_params)
            matches = response.json().get("data", []) if response.status_code == 200 else []

        # 5. Format the Outbound WhatsApp Message using the Commission Shield
        if not matches:
            reply_text = (
                "We have received your requirements! Our local team is currently scanning "
                "our offline network and will get back to you shortly with options."
            )
        else:
            reply_text = f"Great news! We found {len(matches)} verified properties matching your criteria right now:\n\n"
            
            for idx, match in enumerate(matches, 1):
                safe_data = mask_property_for_client(match)
                reply_text += (
                    f"*{idx}. {safe_data.get('bhk')}BHK in {safe_data.get('general_area')}*\n"
                    f"Rent: ₹{safe_data.get('price')} | Deposit: ₹{safe_data.get('deposit')}\n"
                    f"Furnishing: {str(safe_data.get('furnishing')).title()}\n"
                    f"Tenant Preference: {str(safe_data.get('tenant_preference')).title()}\n\n"
                )
                
            reply_text += "Reply with the number of the property you'd like to visit, and our team will coordinate the site visit!"

        # Print the final output for terminal debugging
        print("\n=== OUTBOUND WHATSAPP PAYLOAD ===")
        print(f"To: {sender_phone}")
        print(reply_text)
        print("=================================\n")
        
        # TODO: Inject your actual WhatsApp Meta API call here!
        # send_whatsapp_message(sender_phone, reply_text)

        # 6. Close out the event successfully
        db["webhook_events"].update_one(
            {"event_id": event_id},
            {"$set": {"processing_status": "completed", "processed_at": datetime.now(timezone.utc)}}
        )
        return f"Success: AI Processed & Matched Lead {lead_id}."
        
    except Exception as e:
        db["webhook_events"].update_one(
            {"event_id": event_id},
            {"$set": {"processing_status": "failed", "error_log": str(e)}}
        )
        return f"Error on '{event_id}': {str(e)}"