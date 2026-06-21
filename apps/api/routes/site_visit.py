# apps/api/routes/site_visit.py
from fastapi import APIRouter, HTTPException, status
from typing import List
from apps.api.schemas.site_visit_schemas import SiteVisitCreate, SiteVisitUpdate, SiteVisitResponse, VisitStatus
from apps.api.repositories.site_visit_repository import site_visit_repo

router = APIRouter(prefix="/site-visits", tags=["Site Visits Operations"])


@router.post("/", response_model=SiteVisitResponse, status_code=status.HTTP_201_CREATED)
async def create_site_visit(visit: SiteVisitCreate):
    """Accepts a payload matching the creation schema, writes it, and returns the document."""
    try:
        new_visit = await site_visit_repo.insert_site_visit(
            lead_id=visit.lead_id,
            property_id=visit.property_id,
            scheduled_at=visit.scheduled_at,
            notes=visit.notes
        )
        return new_visit
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/lead/{lead_id}", response_model=List[SiteVisitResponse])
async def get_lead_visits(lead_id: str):
    """Returns a list of all visits for a specific client."""
    try:
        visits = await site_visit_repo.get_site_visits_by_lead(lead_id)
        return visits
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/active", response_model=List[SiteVisitResponse])
async def get_active_site_visits():
    """Returns all upcoming scheduled appointments."""
    try:
        visits = await site_visit_repo.get_all_active_site_visits()
        return visits
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/{id}", response_model=SiteVisitResponse)
async def patch_site_visit(id: str, update_data: SiteVisitUpdate):
    """
    Accepts status updates and custom text updates, dynamically pushing the lead's state
    to 'VISIT_SCHEDULED' or 'VISIT_COMPLETED' depending on the modification payload.
    """
    try:
        status_val = update_data.status.value if update_data.status else None
        updated_visit = await site_visit_repo.update_site_visit_status(
            visit_id=id,
            status=status_val,
            notes=update_data.notes
        )
        if not updated_visit:
            raise HTTPException(status_code=404, detail="Site visit not found")

        # Dynamically push the lead's state to 'VISIT_SCHEDULED' or 'VISIT_COMPLETED' in the master collection
        if update_data.status:
            lead_id = updated_visit.get("lead_id")
            if lead_id:
                from apps.api.repositories.lead_repository import LeadRepository
                from apps.api.schemas.lead_schemas import LeadUpdate
                lead_repo = LeadRepository()

                lead_status = None
                if update_data.status == VisitStatus.SCHEDULED:
                    lead_status = "VISIT_SCHEDULED"
                elif update_data.status == VisitStatus.COMPLETED:
                    lead_status = "VISIT_COMPLETED"

                if lead_status:
                    await lead_repo.update_lead(lead_id, LeadUpdate(status=lead_status))

        return updated_visit
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
