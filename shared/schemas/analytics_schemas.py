# shared/schemas/analytics_schemas.py
from pydantic import BaseModel, Field
from datetime import datetime

class LocalitySnapshot(BaseModel):
    locality: str = Field(..., description="Target sub-market area")
    city: str = Field(..., description="City location")
    average_price_sqft: float
    total_active_listings: int
    market_velocity: str = Field(..., description="High, Medium, or Low based on velocity trends")
    last_updated: datetime = Field(default_factory=datetime.utcnow)