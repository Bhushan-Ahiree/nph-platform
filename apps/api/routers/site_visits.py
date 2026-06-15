from fastapi import APIRouter, HTTPException, status
from typing import List
from apps.api.schemas.site_visit_schemas import SiteVisitCreate, SiteVisitUpdate, SiteVisitResponse
from apps.api.repositories.site_visit_repository import site_visit_repo

router = APIRouter(prefix="/site-visits", tags=["Site Visits Operations"])

@router.post("/", response_model=SiteVisitResponse, status_code=status.HTTP_201_CREATED)
async def request_site_visit(visit: SiteVisitCreate):
    """
    Called by the Webhook Worker when a lead replies "I want to visit option 2".
    Generates the ₹100 fee expectation and alerts Mom.
    """
    try:
        new_visit = await site_visit_repo.create_visit(visit)
        return new_visit
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.patch("/{visit_id}", response_model=SiteVisitResponse)
async def update_site_visit_status(visit_id: str, update_data: SiteVisitUpdate):
    """
    Called by Mom's Dashboard when she finishes the physical visit, 
    collects the fee, and marks them as INTERESTED.
    """
    updated_visit = await site_visit_repo.update_visit(visit_id, update_data)
    if not updated_visit:
        raise HTTPException(status_code=404, detail="Site visit not found")
    return updated_visit

@router.get("/lead/{lead_id}", response_model=List[SiteVisitResponse])
async def get_lead_visits(lead_id: str):
    """Fetches history to see if this lead has a habit of ghosting visits."""
    visits = await site_visit_repo.get_visits_for_lead(lead_id)
    return visits