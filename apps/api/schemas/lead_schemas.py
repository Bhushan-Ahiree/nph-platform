# apps/api/schemas/lead_schemas.py
from enum import Enum
from pydantic import BaseModel, Field, EmailStr, model_validator
from typing import Optional, List, Any
from datetime import datetime, timezone


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

    @model_validator(mode="before")
    @classmethod
    def heal_legacy_data(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            if hasattr(data, "model_dump"):
                data = data.model_dump()
            elif hasattr(data, "dict"):
                data = data.dict()
            elif hasattr(data, "__dict__"):
                data = data.__dict__
            else:
                return data

        data = dict(data)
        
        # 1. Map 'id'
        if "id" not in data:
            if "phone" in data:
                data["id"] = str(data["phone"])
            elif "lead_id" in data:
                identities = data.get("identities", [])
                phone = None
                if isinstance(identities, list):
                    for identity in identities:
                        if isinstance(identity, dict) and identity.get("type") == "phone":
                            phone = identity.get("value")
                data["id"] = str(phone) if phone else str(data["lead_id"])
            else:
                data["id"] = "unknown"

        # 2. Map 'status'
        if "status" not in data or not data["status"]:
            data["status"] = LeadStatus.DISCOVERY

        # 3. Instantiate 'requirements' from root-level legacy keys
        if "requirements" not in data or not isinstance(data["requirements"], dict):
            reqs = {}
            for key in ["city", "area", "bhk", "min_price", "max_price", "property_type", "listing_type"]:
                if key in data:
                    reqs[key] = data[key]
            data["requirements"] = reqs

        # 4. Timestamps
        now = datetime.now(timezone.utc)
        if "created_at" not in data or not data["created_at"]:
            data["created_at"] = now
        if "updated_at" not in data or not data["updated_at"]:
            data["updated_at"] = now

        return data

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}
        populate_by_name = True