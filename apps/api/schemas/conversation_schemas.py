# apps/api/schemas/conversation_schemas.py
from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime

class MessageBlock(BaseModel):
    role: str = Field(..., pattern="^(user|assistant|system)$", description="Role of the message author")
    content: str = Field(..., min_length=1, description="Raw text content of the message")
    timestamp: datetime = Field(default_factory=datetime.utcnow)

class ConversationAppend(BaseModel):
    role: str = Field(..., pattern="^(user|assistant|system)$")
    content: str = Field(..., min_length=1)

class ConversationResponse(BaseModel):
    lead_id: str
    phone: str = Field(..., pattern=r"^\d{10,12}$")
    channel: str = "whatsapp"
    messages: List[MessageBlock]
    updated_at: datetime

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}