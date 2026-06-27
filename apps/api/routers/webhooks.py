from fastapi import APIRouter, HTTPException, Query, status, Request, Response
from apps.api.schemas.webhook_event import WebhookEventCreate
from apps.api.repositories.webhook_event_repository import WebhookEventRepository
from apps.worker.tasks.webhook_tasks import process_incoming_message_event
import os

router = APIRouter(prefix="/webhooks", tags=["Meta Automation Gateways"])
repo = WebhookEventRepository()

@router.get("/whatsapp")
@router.get("/instagram")
async def meta_security_handshake(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
    hub_verify_token: str = Query(None, alias="hub.verify_token")
):
    """Executes the standard structural security verification handshake with Meta's servers."""
    local_verify_token = os.getenv("META_VERIFY_TOKEN", "<redacted-verify-token>")
    
    if hub_mode == "subscribe" and hub_verify_token == local_verify_token:
        print("[Webhook Verified] Meta successfully connected to NPH Local Environment.")
        return Response(content=hub_challenge, media_type="text/plain")
        
    raise HTTPException(status_code=403, detail="Verification token mapping mismatch.")

@router.post("/whatsapp", status_code=status.HTTP_202_ACCEPTED)
@router.post("/instagram", status_code=status.HTTP_202_ACCEPTED)
async def process_async_meta_payload(request: Request):
    """Ingests Meta's deeply nested payload, normalizes it, and pushes to Celery."""
    try:
        # Get the raw Meta JSON
        payload = await request.json()
        
        # 1. Ensure it's actually a WhatsApp message (ignore read receipts, etc.)
        if payload.get("object") == "whatsapp_business_account":
            for entry in payload.get("entry", []):
                for change in entry.get("changes", []):
                    value = change.get("value", {})
                    
                    # If there is a message, extract the core data
                    if "messages" in value:
                        msg = value["messages"][0]
                        # Only process text messages for now
                        if msg.get("type") == "text":
                            sender = msg.get("from")
                            text = msg.get("text", {}).get("body", "")
                            
                            # 2. Convert Meta's mess into your clean Pydantic schema
                            normalized_event = WebhookEventCreate(
                                platform="whatsapp",
                                event_type="message",
                                sender=sender,
                                payload={"text": text}
                            )
                            
                            # 3. Store and pass to Celery
                            event_record = await repo.insert_raw_event(normalized_event)
                            process_incoming_message_event.delay(event_record["event_id"])
                            
        # Always return a 2xx status so Meta doesn't disable your webhook!
        return {"status": "accepted"}
    except Exception as e:
        print(f"Meta Normalization Error: {e}")
        return {"status": "accepted"}