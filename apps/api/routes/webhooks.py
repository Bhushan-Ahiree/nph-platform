# apps/api/routes/webhooks.py
from fastapi import APIRouter, HTTPException, Query, status, BackgroundTasks
from apps.api.schemas.webhook_event import WebhookEventCreate, WebhookEventResponse
from apps.api.repositories.webhook_event_repository import WebhookEventRepository
from apps.worker.tasks.webhook_tasks import process_incoming_message_event  # Task placeholder
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
        # Returning only the challenge value satisfies Meta's verification checks
        from fastapi.responses import Response
        return Response(content=hub_challenge, media_type="text/plain")
        
    raise HTTPException(status_code=403, detail="Verification token mapping mismatch.")

@router.post("/whatsapp", status_code=status.HTTP_202_ACCEPTED)
@router.post("/instagram", status_code=status.HTTP_202_ACCEPTED)
async def process_async_meta_payload(payload: WebhookEventCreate):
    """Ingests incoming structural elements instantly, commits them to disk, and pushes to Celery."""
    try:
        # 1. Store raw event in database immediately
        event_record = await repo.insert_raw_event(payload)
        
        # 2. Asynchronously push to your background execution stack
        # process_incoming_message_event.delay(event_record["event_id"])
        
        # 3. Return 202 Accepted to clear the webhook connection pool instantly
        return {"status": "accepted", "event_id": event_record["event_id"]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Webhook ingestion safety failure: {str(e)}")