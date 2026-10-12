# apps/api/schemas/broker_schemas.py
from datetime import datetime, timezone
from typing import Optional
from pydantic import BaseModel, Field, ConfigDict

class BrokerProfileBase(BaseModel):
    name: str
    company: Optional[str] = None
    properties_posted: int = 0
    verified_properties: int = 0
    expired_properties: int = 0
    reliability_score: int = 100
    last_seen_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class BrokerProfileCreate(BaseModel):
    phone: str
    name: str
    company: Optional[str] = None

class BrokerProfileResponse(BrokerProfileBase):
    id: str = Field(..., alias="_id")

    model_config = ConfigDict(populate_by_name=True, json_encoders={datetime: lambda v: v.isoformat()})
