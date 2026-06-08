# apps/api/schemas/match_schemas.py
from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime

class MatchResponse(BaseModel):
    match_id: str
    lead_id: str
    property_id: str
    score: int = Field(..., ge=0, le=100)
    reasons: List[str]
    sent: bool = False
    viewed: bool = False
    shortlisted: bool = False
    site_visit_requested: bool = False
    created_at: datetime

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}