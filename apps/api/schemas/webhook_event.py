# apps/api/schemas/webhook_event.py
from pydantic import BaseModel, Field
from typing import Dict, Any, Optional
from datetime import datetime, timezone

class WebhookEventCreate(BaseModel):
    platform: str = Field(..., pattern="^(whatsapp|instagram)$")
    event_type: str = Field("message")
    sender: str = Field(..., pattern=r"^\d{10,15}$", description="Clean string format client cell")
    payload: Dict[str, Any]

class WebhookEventResponse(BaseModel):
    event_id: str
    platform: str
    event_type: str
    sender: str
    payload: Dict[str, Any]
    processing_status: str = "pending"
    received_at: datetime

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}

class LeadActivityLog(BaseModel):
    lead_id: str
    activity_type: str = Field(..., description="e.g., message_received, match_sent, site_visit_booked")
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))