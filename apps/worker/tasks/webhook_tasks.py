# apps/worker/tasks/webhook_tasks.py
import os
from celery import Celery
from pymongo import MongoClient
from datetime import datetime

# Initialize raw client link targeting your worker container execution bounds
redis_url = os.getenv("REDIS_URL", "redis://redis:6379/0")
celery_app = Celery("nph_tasks", broker=redis_url, backend=redis_url)

@celery_app.task(name="tasks.webhook_tasks.process_incoming_message_event")
def process_incoming_message_event(event_id: str):
    """Background task engine that safely executes heavy logic out-of-band."""
    mongo_url = os.getenv("MONGO_URL") or os.getenv("MONGO_URI")
    client = MongoClient(mongo_url)
    db = client["nph_core"]
    
    event = db["webhook_events"].find_one({"event_id": event_id})
    if not event:
        return f"Failure: Event '{event_id}' not found."

    db["webhook_events"].update_one(
        {"event_id": event_id},
        {"$set": {"processing_status": "processing"}}
    )

    try:
        # This is where your Day 6 AI Parsing pipelines will sit safely out-of-band.
        # It handles extracting parameters from plain text without blocking the webhooks.
        
        # Mark event as complete once processing finishes
        db["webhook_events"].update_one(
            {"event_id": event_id},
            {"$set": {"processing_status": "completed", "processed_at": datetime.utcnow()}}
        )
        return f"Success: Event '{event_id}' processed cleanly."
        
    except Exception as e:
        db["webhook_events"].update_one(
            {"event_id": event_id},
            {"$set": {"processing_status": "failed", "error_log": str(e)}}
        )
        return f"Error: Failed to process event '{event_id}': {str(e)}"