# shared/schemas/property.py
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone

class Coordinates(BaseModel):
    lat: float = 0.0
    lng: float = 0.0

class Location(BaseModel):
    city: str = Field(..., description="City of the property, e.g., Pune, Mumbai, Nashik")
    locality: str = Field(..., description="Specific neighborhood or area")
    coordinates: Optional[Coordinates] = None

class PropertyBase(BaseModel):
    title: str = Field(..., min_length=5, max_length=150)
    property_type: str = Field(..., description="e.g., Apartment, Villa, Plot")
    listing_type: str = Field(..., description="e.g., Buy, Rent")
    price: float = Field(..., ge=0, description="Price in INR")
    area_sqft: float = Field(..., ge=0)
    
    location: Location
    
    features: List[str] = []
    amenities: List[str] = []
    images: List[str] = []
    videos: List[str] = []
    
    # Using Dict for flexibility right now, can be strictly typed later
    builder: Optional[Dict[str, Any]] = None
    agent: Optional[Dict[str, Any]] = None
    source: Optional[Dict[str, Any]] = None
    
    status: str = Field(default="active", description="active, sold, inactive")

class PropertyCreate(PropertyBase):
    """Model used when receiving a new property from a scraper or API"""
    pass

class PropertyDB(PropertyBase):
    """Model used when returning a property from the database"""
    id: str = Field(alias="_id") # Maps MongoDB's internal _id to id
    property_id: str
    created_at: datetime
    updated_at: datetime

    class Config:
        populate_by_name = True