# apps/api/schemas/recommendation_schemas.py
from pydantic import BaseModel, Field, model_validator
from typing import Literal, Any
from datetime import datetime, timezone

RecommendationEventLiteral = Literal[
    'SENT',
    'VIEWED',
    'INTERESTED',
    'VISIT_REQUESTED',
    'VISIT_SCHEDULED',
    'VISIT_COMPLETED',
    'CLOSED',
    'REJECTED'
]

class RecommendationEventCreate(BaseModel):
    lead_id: str
    property_id: str
    match_score: int
    event: RecommendationEventLiteral

class RecommendationEventResponse(BaseModel):
    id: str = Field(..., alias="id")
    lead_id: str
    property_id: str
    match_score: int
    event: RecommendationEventLiteral
    created_at: datetime

    @model_validator(mode="before")
    @classmethod
    def populate_ids(cls, data: Any) -> Any:
        if isinstance(data, dict):
            # Enforce stringification of MongoDB ObjectIds
            if "_id" in data and "id" not in data:
                data["id"] = str(data["_id"])
            elif "id" in data and "_id" not in data:
                data["_id"] = data["id"]
        return data

    model_config = {
        "populate_by_name": True,
        "json_encoders": {datetime: lambda dt: dt.isoformat()}
    }
