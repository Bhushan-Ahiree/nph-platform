# apps/api/schemas/site_visit_schemas.py
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from enum import Enum


class VisitStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NOSHOW = "NOSHOW"


class SiteVisitCreate(BaseModel):
    lead_id: str
    property_id: str
    scheduled_at: datetime
    notes: Optional[str] = None


class SiteVisitUpdate(BaseModel):
    status: Optional[VisitStatus] = None
    notes: Optional[str] = None
    scheduled_at: Optional[datetime] = None


class SiteVisitResponse(BaseModel):
    id: str = Field(alias="id")
    lead_id: str
    property_id: str
    scheduled_at: datetime
    status: VisitStatus = VisitStatus.SCHEDULED
    notes: Optional[str] = None
    created_at: datetime

    model_config = {"populate_by_name": True}