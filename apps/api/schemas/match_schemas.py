# apps/api/schemas/match_schemas.py
from pydantic import BaseModel, Field
from typing import List, Literal
from datetime import datetime


class MatchCreate(BaseModel):
    lead_id: str
    property_ids: List[str]
    status: Literal["SENT", "VIEWED", "ARCHIVED"] = "SENT"


class MatchUpdate(BaseModel):
    status: Literal["SENT", "VIEWED", "ARCHIVED"]


class MatchResponse(BaseModel):
    id: str = Field(alias="match_id")
    lead_id: str
    property_ids: List[str]
    status: Literal["SENT", "VIEWED", "ARCHIVED"]
    generated_at: datetime

    model_config = {"populate_by_name": True}