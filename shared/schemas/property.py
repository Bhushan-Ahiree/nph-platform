# shared/schemas/property.py
from pydantic import BaseModel, Field, constr
from typing import List, Optional, Dict, Any
from datetime import datetime

class Coordinates(BaseModel):
    lat: float = 0.0
    lng: float = 0.0

class Location(BaseModel):
    city: str = Field(..., description="City of the property, e.g., Pune, Mumbai, Nashik")
    locality: str = Field(..., description="Specific neighborhood or area")
    coordinates: Optional[Coordinates] = None

class Contact(BaseModel):
    name: str = Field(..., description="Name of the point of contact")
    phone: str = Field(..., min_length=10, max_length=15, description="Primary contact number")
    type: str = Field(..., description="Owner, Broker, or Builder")

class PropertyBase(BaseModel):
    title: str = Field(..., min_length=5, max_length=150)
    property_type: str = Field(..., description="Apartment, Villa, Plot, Commercial")
    listing_type: str = Field(..., description="Buy, Rent")
    
    # Financials
    price: float = Field(..., ge=0, description="Price in INR")
    maintenance_monthly: Optional[float] = Field(default=0.0)
    deposit_amount: Optional[float] = Field(default=0.0, description="For rentals")
    
    # Area (MahaRERA Compliant)
    carpet_area_sqft: float = Field(..., ge=0)
    super_area_sqft: Optional[float] = None
    
    # Status & Compliance
    construction_status: str = Field(default="Ready to Move", description="Under Construction, Ready to Move, New Launch")
    possession_date: Optional[str] = Field(default=None, description="MM-YYYY for under construction")
    rera_id: Optional[str] = None
    
    # Indian Market Specifics
    furnishing_status: str = Field(default="Unfurnished", description="Unfurnished, Semi-Furnished, Fully Furnished")
    parking_covered: int = Field(default=0)
    parking_open: int = Field(default=0)
    facing: Optional[str] = Field(default=None, description="Vastu direction")
    
    # Nested Data
    location: Location
    contact: Contact
    
    features: List[str] = []
    amenities: List[str] = []
    images: List[str] = []
    
    # Internal System Fields
    status: str = Field(default="active", description="active, sold, inactive")

class PropertyCreate(PropertyBase):
    pass

class PropertyDB(PropertyBase):
    id: str = Field(alias="_id") 
    property_id: str
    created_at: datetime
    updated_at: datetime

    class Config:
        populate_by_name = True