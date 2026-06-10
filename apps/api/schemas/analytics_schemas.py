# apps/api/schemas/analytics_schemas.py
from pydantic import BaseModel
from typing import Dict

class PipelineSummaryResponse(BaseModel):
    total_active_leads: int
    hot_leads_count: int  # Score >= 70
    warm_leads_count: int # Score between 40 and 69
    cold_leads_count: int # Score < 40
    site_visits_booked: int
    site_visits_paid: int
    conversion_rate_percentage: float
    total_deal_revenue: float