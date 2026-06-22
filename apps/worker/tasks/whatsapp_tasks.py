# apps/worker/tasks/whatsapp_tasks.py
import os
import uuid
import logging
from datetime import datetime, timezone
from celery import shared_task
from pymongo import MongoClient
from services.whatsapp.client import MetaWhatsAppClient

logger = logging.getLogger(__name__)

# Resolve connection pool targeting database cluster
mongo_url = os.getenv("MONGO_URL") or os.getenv("MONGO_URI")
client = MongoClient(mongo_url)
db = client["nph_core"]

@shared_task(
    name="tasks.whatsapp_tasks.send_whatsapp_message",
    bind=True,
    max_retries=3,
    autoretry_for=(Exception,),
    retry_backoff=5,
    retry_jitter=True
)
def send_whatsapp_message(self, recipient_phone: str, text: str):
    """
    Asynchronous Celery task for executing outbound Meta Cloud API message delivery.
    Logs transaction metadata to the 'whatsapp_message_logs' collection.
    """
    task_id = self.request.id
    logger.info(f"[Outbound WhatsApp] [{task_id}] Queueing message for: {recipient_phone}")
    
    log_id = f"outmsg_{uuid.uuid4().hex[:10]}"
    now = datetime.now(timezone.utc)
    
    # Initialize message log entry in pending state
    message_log = {
        "log_id": log_id,
        "recipient_phone": recipient_phone,
        "direction": "outbound",
        "message_type": "text",
        "content": text,
        "status": "pending",
        "created_at": now,
        "sent_at": None,
        "meta_message_id": None,
        "error": None
    }
    
    try:
        # Create log record before attempting request to ensure observability
        db["whatsapp_message_logs"].insert_one(message_log)
    except Exception as db_err:
        logger.warning(f"[Outbound WhatsApp] [{task_id}] Pre-log database write failed: {db_err}")
        
    try:
        # Initiate api request payload delivery
        whatsapp_client = MetaWhatsAppClient()
        result = whatsapp_client.send_text_message(to=recipient_phone, text=text)
        
        meta_id = result.get("messages", [{}])[0].get("id")
        
        # Commit updated confirmation records back to database
        db["whatsapp_message_logs"].update_one(
            {"log_id": log_id},
            {
                "$set": {
                    "status": "sent",
                    "sent_at": datetime.now(timezone.utc),
                    "meta_message_id": meta_id
                }
            }
        )
        logger.info(f"[Outbound WhatsApp] [{task_id}] Successfully dispatched. Meta ID: {meta_id}")
        return {"status": "sent", "log_id": log_id, "meta_id": meta_id}
        
    except Exception as exc:
        logger.error(f"[Outbound WhatsApp] [{task_id}] Delivery failure: {str(exc)}")
        
        # Log failure state on current document
        db["whatsapp_message_logs"].update_one(
            {"log_id": log_id},
            {
                "$set": {
                    "status": "failed",
                    "error": str(exc)
                }
            }
        )
        
        # Raise for Celery to run automatic retry logic
        raise exc
