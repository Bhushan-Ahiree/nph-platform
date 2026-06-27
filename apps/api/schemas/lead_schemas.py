# apps/api/schemas/lead_schemas.py
from enum import Enum
from pydantic import BaseModel, Field, EmailStr, model_validator
from typing import Optional, List, Any, Literal
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


class LeadType(str, Enum):
    """Distinguishes the role of the person behind the lead."""
    CLIENT = "CLIENT"               # End-customer looking for a property
    BROKER = "BROKER"               # Broker searching on behalf of a client
    OWNER = "OWNER"                 # Owner offering a property (reclassify to supply)


class LeadTemperature(str, Enum):
    HOT = "HOT"
    WARM = "WARM"
    COLD = "COLD"


class LeadSource(str, Enum):
    """Channel attribution — where the lead originated."""
    WHATSAPP = "whatsapp"
    INSTAGRAM = "instagram"
    WEBSITE = "website"
    MANUAL = "manual"


class LeadRequirements(BaseModel):
    city: Optional[Literal["Nashik", "Pune", "Mumbai"]] = None
    area: Optional[str] = None
    bhk: Optional[int] = None
    min_price: Optional[float] = None
    max_price: Optional[float] = None
    property_type: Optional[str] = None
    listing_type: Optional[Literal["rent", "buy", "sale"]] = None


class LeadCreate(BaseModel):
    id: str = Field(..., description="Unique identifier linked to user phone (e.g. wa_id)")
    status: LeadStatus = LeadStatus.DISCOVERY
    lead_type: LeadType = LeadType.CLIENT
    source: LeadSource = LeadSource.WHATSAPP
    requirements: LeadRequirements = Field(default_factory=LeadRequirements)
    name: Optional[str] = None
    email: Optional[EmailStr] = None
    priority_score: int = 0
    lead_temperature: LeadTemperature = LeadTemperature.COLD
    preferred_locations: Optional[List[str]] = None
    move_in_date: Optional[str] = None
    last_contacted_at: Optional[datetime] = None
    follow_up_count: int = 0
    assigned_to: Optional[str] = None
    next_follow_up_at: Optional[datetime] = None


class LeadUpdate(BaseModel):
    status: Optional[LeadStatus] = None
    lead_type: Optional[LeadType] = None
    source: Optional[LeadSource] = None
    requirements: Optional[LeadRequirements] = None
    name: Optional[str] = None
    email: Optional[EmailStr] = None
    priority_score: Optional[int] = None
    lead_temperature: Optional[LeadTemperature] = None
    preferred_locations: Optional[List[str]] = None
    move_in_date: Optional[str] = None
    last_contacted_at: Optional[datetime] = None
    follow_up_count: Optional[int] = None
    assigned_to: Optional[str] = None
    next_follow_up_at: Optional[datetime] = None


class LeadResponse(BaseModel):
    id: str
    status: LeadStatus
    lead_type: LeadType = LeadType.CLIENT
    source: LeadSource = LeadSource.WHATSAPP
    requirements: LeadRequirements
    name: Optional[str] = None
    email: Optional[EmailStr] = None
    priority_score: int = 0
    lead_temperature: LeadTemperature = LeadTemperature.COLD
    preferred_locations: Optional[List[str]] = None
    move_in_date: Optional[str] = None
    last_contacted_at: Optional[datetime] = None
    follow_up_count: int = 0
    assigned_to: Optional[str] = None
    next_follow_up_at: Optional[datetime] = None
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

        # 4. Default lead_type and source for legacy documents
        if "lead_type" not in data or not data["lead_type"]:
            data["lead_type"] = LeadType.CLIENT
        if "source" not in data or not data["source"]:
            data["source"] = LeadSource.WHATSAPP
            
        # 5. Enrichment and scoring defaults
        if "priority_score" not in data:
            data["priority_score"] = 0
        if "lead_temperature" not in data:
            data["lead_temperature"] = LeadTemperature.COLD
        if "preferred_locations" not in data:
            data["preferred_locations"] = None
        if "move_in_date" not in data:
            data["move_in_date"] = None
        if "last_contacted_at" not in data:
            data["last_contacted_at"] = None
        if "follow_up_count" not in data:
            data["follow_up_count"] = 0
        if "assigned_to" not in data:
            data["assigned_to"] = None
        if "next_follow_up_at" not in data:
            data["next_follow_up_at"] = None

        # 5. Timestamps
        now = datetime.now(timezone.utc)
        if "created_at" not in data or not data["created_at"]:
            data["created_at"] = now
        if "updated_at" not in data or not data["updated_at"]:
            data["updated_at"] = now

        return data

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}
        populate_by_name = True