# apps/api/schemas/lead_schemas.py
from enum import Enum
from pydantic import BaseModel, Field, EmailStr
from typing import Optional, List
from datetime import datetime


class LeadStatus(str, Enum):
    DISCOVERY = "DISCOVERY"
    PARTIAL_REQUIREMENTS = "PARTIAL_REQUIREMENTS"
    MATCHABLE = "MATCHABLE"
    PROPERTIES_SENT = "PROPERTIES_SENT"
    VISIT_REQUESTED = "VISIT_REQUESTED"
    VISIT_SCHEDULED = "VISIT_SCHEDULED"
    VISIT_COMPLETED = "VISIT_COMPLETED"
    CLOSED = "CLOSED"


class LeadRequirements(BaseModel):
    city: Optional[str] = None
    area: Optional[str] = None
    bhk: Optional[int] = None
    min_price: Optional[float] = None
    max_price: Optional[float] = None
    property_type: Optional[str] = None
    listing_type: Optional[str] = None


class LeadCreate(BaseModel):
    id: str = Field(..., description="Unique identifier linked to user phone (e.g. wa_id)")
    status: LeadStatus = LeadStatus.DISCOVERY
    requirements: LeadRequirements = Field(default_factory=LeadRequirements)
    name: Optional[str] = None
    email: Optional[EmailStr] = None


class LeadUpdate(BaseModel):
    status: Optional[LeadStatus] = None
    requirements: Optional[LeadRequirements] = None
    name: Optional[str] = None
    email: Optional[EmailStr] = None


class LeadResponse(BaseModel):
    id: str
    status: LeadStatus
    requirements: LeadRequirements
    name: Optional[str] = None
    email: Optional[EmailStr] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}
        populate_by_name = True