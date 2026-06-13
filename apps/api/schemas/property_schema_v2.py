# apps/api/schemas/property_schema_v2.py
from datetime import datetime
from typing import List, Optional, Literal
from pydantic import BaseModel, Field

class PropertySource(BaseModel):
    type: Literal["broker_group", "owner_network", "manual", "scraping"] = "broker_group"
    group_name: Optional[str] = None
    broker_name: Optional[str] = None
    broker_phone: Optional[str] = None

class PropertyAvailability(BaseModel):
    status: Literal["active", "rented", "sold", "inactive"] = "active"
    last_verified_at: datetime = Field(default_factory=datetime.utcnow)
    verified_by: Literal["mom", "bhushan", "automated"] = "automated"

class PropertyRentalDetails(BaseModel):
    deposit: Optional[int] = 0
    preferred_tenant: Literal["family", "bachelor", "any"] = "any"
    furnishing: Literal["unfurnished", "semi-furnished", "fully-furnished"] = "unfurnished"

class PropertyIntelligence(BaseModel):
    hot_property: bool = False
    duplicate_count: int = 0
    source_confidence: int = 100

class PropertySchemaV2(BaseModel):
    title: str
    description: Optional[str] = None
    property_type: Literal["apartment", "villa", "plot", "commercial"] = "apartment"
    listing_type: Literal["rent", "buy"] = "rent"
    
    # Geographic Data
    city: Literal["Nashik", "Pune", "Mumbai"] = "Nashik"
    area: str  # e.g., "Indira Nagar", "College Road", "Kothrud"
    
    # Financials & Structure
    price: int = Field(..., description="Rent amount or full buying price")
    bhk: int = Field(default=0, description="Number of bedrooms")
    parking: bool = False
    carpet_area_sqft: Optional[int] = None
    
    # Operational Extensions (NPH V2)
    source: PropertySource
    availability: PropertyAvailability = Field(default_factory=PropertyAvailability)
    rental_details: PropertyRentalDetails = Field(default_factory=PropertyRentalDetails)
    intelligence: PropertyIntelligence = Field(default_factory=PropertyIntelligence)
    
    raw_message: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)