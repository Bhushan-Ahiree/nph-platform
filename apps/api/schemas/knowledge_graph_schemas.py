# apps/api/schemas/knowledge_graph_schemas.py
from datetime import datetime, timezone
from typing import List, Optional, Literal, Any, Dict
from pydantic import BaseModel, Field, model_validator


class BuilderNode(BaseModel):
    """
    Canonical representation of a real estate builder or developer entity in the Knowledge Graph.
    Acts as a single source of truth for reputation, aliases, and project portfolio.
    """
    id: str = Field(..., alias="_id")
    builder_id: str
    canonical_name: str
    aliases: List[str] = Field(default_factory=list)
    city: Literal["Nashik", "Pune", "Mumbai"] = "Nashik"
    established_year: Optional[int] = None
    reputation_score: int = Field(default=100, ge=0, le=100, description="Reputation and delivery quality score")
    active_projects_count: int = Field(default=0)
    total_projects_count: int = Field(default=0)
    verified: bool = Field(default=False)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    model_config = {"populate_by_name": True, "extra": "ignore"}

    @model_validator(mode="before")
    @classmethod
    def populate_builder_id(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "_id" in data and "id" not in data:
                data["id"] = str(data["_id"])
            elif "id" in data and "_id" not in data:
                data["_id"] = data["id"]
            if "builder_id" not in data and "id" in data:
                data["builder_id"] = data["id"]
            if "aliases" not in data:
                data["aliases"] = []
            if "created_at" not in data:
                data["created_at"] = datetime.now(timezone.utc)
            if "updated_at" not in data:
                data["updated_at"] = datetime.now(timezone.utc)
        return data


class ProjectNode(BaseModel):
    """
    Canonical registry of a real estate project or building society.
    Connects properties to shared master data such as amenities, exact location, and developer identity.
    """
    id: str = Field(..., alias="_id")
    project_id: str
    builder_id: Optional[str] = None
    canonical_name: str
    aliases: List[str] = Field(default_factory=list)
    locality_id: Optional[str] = None
    city: Literal["Nashik", "Pune", "Mumbai"] = "Nashik"
    possession_status: Optional[str] = None
    master_amenities: List[str] = Field(default_factory=list)
    active_properties_count: int = Field(default=0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    model_config = {"populate_by_name": True, "extra": "ignore"}

    @model_validator(mode="before")
    @classmethod
    def populate_project_id(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "_id" in data and "id" not in data:
                data["id"] = str(data["_id"])
            elif "id" in data and "_id" not in data:
                data["_id"] = data["id"]
            if "project_id" not in data and "id" in data:
                data["project_id"] = data["id"]
            if "aliases" not in data:
                data["aliases"] = []
            if "master_amenities" not in data:
                data["master_amenities"] = []
            if "created_at" not in data:
                data["created_at"] = datetime.now(timezone.utc)
            if "updated_at" not in data:
                data["updated_at"] = datetime.now(timezone.utc)
        return data


class LocalityNode(BaseModel):
    """
    Canonical geographic node representing a distinct locality or micro-market.
    Eliminates in-memory alias dictionaries and enables high-performance index lookups instead of regex scans.
    """
    id: str = Field(..., alias="_id")
    locality_id: str
    city: Literal["Nashik", "Pune", "Mumbai"] = "Nashik"
    canonical_name: str
    aliases: List[str] = Field(default_factory=list)
    micro_market: Optional[str] = None
    pin_codes: List[str] = Field(default_factory=list)
    active_properties_count: int = Field(default=0)
    average_price_sqft: Optional[int] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    model_config = {"populate_by_name": True, "extra": "ignore"}

    @model_validator(mode="before")
    @classmethod
    def populate_locality_id(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "_id" in data and "id" not in data:
                data["id"] = str(data["_id"])
            elif "id" in data and "_id" not in data:
                data["_id"] = data["id"]
            if "locality_id" not in data and "id" in data:
                data["locality_id"] = data["id"]
            if "aliases" not in data:
                data["aliases"] = []
            if "pin_codes" not in data:
                data["pin_codes"] = []
            if "created_at" not in data:
                data["created_at"] = datetime.now(timezone.utc)
            if "updated_at" not in data:
                data["updated_at"] = datetime.now(timezone.utc)
        return data


class AmenityNode(BaseModel):
    """
    Global taxonomy node for real estate amenities.
    Maps raw WhatsApp broker amenity strings to canonical IDs with standardized weighting.
    """
    id: str = Field(..., alias="_id")
    amenity_id: str
    canonical_name: str
    display_name: str
    category: Literal["convenience", "security", "leisure", "sports", "general"] = "general"
    aliases: List[str] = Field(default_factory=list)
    weight: int = Field(default=10, description="Match score importance weighting")

    model_config = {"populate_by_name": True, "extra": "ignore"}

    @model_validator(mode="before")
    @classmethod
    def populate_amenity_id(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "_id" in data and "id" not in data:
                data["id"] = str(data["_id"])
            elif "id" in data and "_id" not in data:
                data["_id"] = data["id"]
            if "amenity_id" not in data and "id" in data:
                data["amenity_id"] = data["id"]
            if "aliases" not in data:
                data["aliases"] = []
        return data
