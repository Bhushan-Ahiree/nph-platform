# shared/schemas/property.py
from pydantic import BaseModel, Field, model_validator
from typing import Optional, Any
from datetime import datetime, timezone


class PropertySource(BaseModel):
    """Tracks the origination context of a property listing."""
    type: str = "broker_group"
    group_name: Optional[str] = None
    broker_name: Optional[str] = None
    broker_phone: Optional[str] = None


class PropertyAvailability(BaseModel):
    """Tracks the current lifecycle status of a property listing."""
    status: str = "active"
    last_verified_at: Optional[datetime] = None
    verified_by: str = "automated"


class PropertyRentalDetails(BaseModel):
    """Stores rental-specific financial and preference metadata."""
    deposit: Optional[int] = 0
    preferred_tenant: str = "any"
    furnishing: str = "unfurnished"


class PropertyIntelligence(BaseModel):
    """Internal analytics signals attached to each property document."""
    hot_property: bool = False
    duplicate_count: int = 0
    source_confidence: int = 100


class PropertyBase(BaseModel):
    title: str
    description: Optional[str] = None
    property_type: str = "apartment"
    listing_type: str = "rent"

    # Geographic Data (flat fields aligned to V2 schema)
    city: str = "Nashik"
    area: str

    # Financials & Structure
    price: int = Field(..., description="Rent amount or full buying price")
    bhk: int = Field(default=0, description="Number of bedrooms")
    parking: bool = False
    carpet_area_sqft: Optional[float] = None

    # Nested Operational Extensions
    source: PropertySource = Field(default_factory=PropertySource)
    availability: PropertyAvailability = Field(default_factory=PropertyAvailability)
    rental_details: PropertyRentalDetails = Field(default_factory=PropertyRentalDetails)
    intelligence: PropertyIntelligence = Field(default_factory=PropertyIntelligence)

    raw_message: Optional[str] = None
    status: str = "ACTIVE"
    availability_status: str = "verified"
    last_verified_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    verification_count: int = 1
    confidence_score: int = 100
    broker_phone: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def normalize_legacy_fields(cls, data: Any) -> Any:
        if isinstance(data, dict):
            # 1. Geographic mapping: extract area and city from location object if missing
            if "location" in data and isinstance(data["location"], dict):
                loc = data["location"]
                if "area" not in data and "locality" in loc:
                    data["area"] = loc.get("locality")
                if "city" not in data or data["city"] == "Nashik":
                    loc_city = loc.get("city")
                    if loc_city:
                        data["city"] = loc_city

            # 2. Normalize property_type and listing_type casing
            if "property_type" in data and isinstance(data["property_type"], str):
                data["property_type"] = data["property_type"].lower()
            if "listing_type" in data and isinstance(data["listing_type"], str):
                data["listing_type"] = data["listing_type"].lower()

            # 3. Source Mapping: extract from legacy contact info if source is not populated
            if "source" not in data or not data["source"]:
                contact = data.get("contact")
                if isinstance(contact, dict):
                    data["source"] = {
                        "type": "broker_group" if contact.get("type") == "Agent" else "owner_network",
                        "broker_name": contact.get("name"),
                        "broker_phone": contact.get("phone")
                    }

            # 4. Rental Details Mapping: extract deposit_amount and furnishing_status
            if "rental_details" not in data or not data["rental_details"]:
                deposit = data.get("deposit_amount", 0)
                try:
                    deposit = int(float(deposit))
                except (ValueError, TypeError):
                    deposit = 0

                furnishing = data.get("furnishing_status", "unfurnished")
                if isinstance(furnishing, str):
                    furnishing = furnishing.lower()

                data["rental_details"] = {
                    "deposit": deposit,
                    "furnishing": furnishing,
                    "preferred_tenant": "any"
                }

            # 5. Extract BHK if missing/0 and title exists
            if data.get("bhk", 0) == 0 and "title" in data and isinstance(data["title"], str):
                import re
                match = re.search(r"(\d+)\s*(?:BHK|bhk)", data["title"])
                if match:
                    data["bhk"] = int(match.group(1))

            # 6. Parse parking from parking_covered/parking_open if parking is False
            if not data.get("parking", False):
                parking_covered = data.get("parking_covered", 0)
                parking_open = data.get("parking_open", 0)
                try:
                    if int(parking_covered) > 0 or int(parking_open) > 0:
                        data["parking"] = True
                except (ValueError, TypeError):
                    pass

            # 7. Coerce price if it is float
            if "price" in data:
                try:
                    data["price"] = int(float(data["price"]))
                except (ValueError, TypeError):
                    pass

            # 8. Status mapping to availability
            if "availability" not in data or not data["availability"]:
                status_val = data.get("status", "active")
                data["availability"] = {
                    "status": status_val,
                    "verified_by": "automated"
                }

            # Map raw status to ACTIVE/UNVERIFIED/ARCHIVED
            raw_status = data.get("status")
            if not raw_status and "availability" in data and isinstance(data["availability"], dict):
                raw_status = data["availability"].get("status")

            if raw_status in ["active", "ACTIVE", None]:
                data["status"] = "ACTIVE"
            elif raw_status in ["unverified", "UNVERIFIED"]:
                data["status"] = "UNVERIFIED"
            elif raw_status in ["archived", "ARCHIVED", "rented", "sold", "inactive", "expired"]:
                data["status"] = "ARCHIVED"
            else:
                data["status"] = "ACTIVE"

            # Normalize availability_status and other auditing fields
            if "availability_status" not in data or not data["availability_status"]:
                data["availability_status"] = "verified"
            if "last_verified_at" not in data or not data["last_verified_at"]:
                data["last_verified_at"] = datetime.now(timezone.utc)
            if "verification_count" not in data or not data["verification_count"]:
                data["verification_count"] = 1
            if "confidence_score" not in data or not data["confidence_score"]:
                data["confidence_score"] = 100
            
            # Map broker_phone from source if present and not set
            if "broker_phone" not in data or not data["broker_phone"]:
                source = data.get("source")
                if isinstance(source, dict):
                    data["broker_phone"] = source.get("broker_phone")
        return data


class PropertyCreate(PropertyBase):
    pass


class PropertyDB(PropertyBase):
    id: str = Field(alias="_id")
    property_id: str
    created_at: datetime
    updated_at: datetime

    model_config = {"populate_by_name": True}