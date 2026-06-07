# apps/api/schemas/lead_schemas.py
from pydantic import BaseModel, Field, EmailStr, validator
from typing import Optional, List
from datetime import datetime
import uuid

class LeadConfiguration(BaseModel):
    bhk: int = Field(..., ge=1, le=10, description="Required BHK configuration count")

class LeadCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    phone: str = Field(..., pattern=r"^\d{10,12}$", description="Standardized 10-12 digit mobile format")
    email: Optional[EmailStr] = None
    requirement_type: str = Field(..., pattern="^(rent|buy)$")
    property_type: str = Field(..., pattern="^(apartment|row_house|villa|plot|commercial)$")
    configuration: LeadConfiguration
    preferred_areas: List[str] = Field(..., min_items=1)
    budget_min: float = Field(..., ge=0)
    budget_max: float = Field(..., ge=0)
    furnishing: str = Field("unfurnished", pattern="^(unfurnished|semi|fully)$")
    parking: bool = False
    family_type: str = Field("family", pattern="^(family|bachelors|any)$")
    move_in_date: Optional[str] = Field(None, description="Expected date string format YYYY-MM-DD")
    source: str = Field("whatsapp")
    assigned_to: Optional[str] = None

    @validator("budget_max")
    def validate_budget_range(cls, v, values):
        if "budget_min" in values and v < values["budget_min"]:
            raise ValueError("budget_max cannot be less than budget_min")
        return v

class LeadUpdate(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[EmailStr] = None
    requirement_type: Optional[str] = None
    property_type: Optional[str] = None
    configuration: Optional[LeadConfiguration] = None
    preferred_areas: Optional[List[str]] = None
    budget_min: Optional[float] = None
    budget_max: Optional[float] = None
    furnishing: Optional[str] = None
    parking: Optional[bool] = None
    family_type: Optional[str] = None
    lead_status: Optional[str] = None
    hotness_score: Optional[int] = Field(None, ge=0, le=100)
    follow_up_count: Optional[int] = Field(None, ge=0)
    site_visit_booked: Optional[bool] = None
    site_visit_paid: Optional[bool] = None
    deal_closed: Optional[bool] = None
    deal_value: Optional[float] = None

class LeadResponse(LeadCreate):
    lead_id: str
    lead_status: str = "new"
    hotness_score: int = 0
    follow_up_count: int = 0
    last_contacted_at: Optional[datetime] = None
    site_visit_booked: bool = False
    site_visit_paid: bool = False
    deal_closed: bool = False
    deal_value: float = 0.0
    created_at: datetime

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}