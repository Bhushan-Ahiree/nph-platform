from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from enum import Enum

class VisitStatus(str, Enum):
    REQUESTED = "requested"      # Lead clicked the number, waiting for Mom to confirm time
    SCHEDULED = "scheduled"      # Time locked in
    COMPLETED = "completed"      # Mom showed the flat
    NO_SHOW = "no_show"          # Lead ghosted (Reduces Lead Score)
    CANCELED = "canceled"        # Mutually canceled

class PostVisitOutcome(str, Enum):
    PENDING = "pending"          # Visit hasn't happened yet
    INTERESTED = "interested"    # Moving to negotiation
    NOT_INTERESTED = "not_interested" # Lead rejected it
    DEAL_CLOSED = "deal_closed"  # Revenue event!

class SiteVisitBase(BaseModel):
    lead_id: str
    property_id: str
    scheduled_at: Optional[datetime] = None
    assigned_to: str = "mom" # Hardcoded for now, can expand if you hire staff
    
    # Financials
    visit_fee_collected: bool = False
    visit_fee_amount: int = 100
    
    # Denormalized Analytics Data (Stamped at creation)
    broker_name: Optional[str] = None
    area: str 

class SiteVisitCreate(SiteVisitBase):
    pass

class SiteVisitResponse(SiteVisitBase):
    id: str = Field(alias="_id")
    status: VisitStatus = VisitStatus.REQUESTED
    outcome: PostVisitOutcome = PostVisitOutcome.PENDING
    feedback_notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime