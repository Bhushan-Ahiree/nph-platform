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
    Accepts status updates, monetization variables, and custom text updates.
    If the deal is closed, initiates an atomic cascade to close the lead and archive the property.
    """
    try:
        from shared.utils.database import db
        
        is_completed_deal = (update_data.status == VisitStatus.COMPLETED and update_data.deal_closed is True)

        if is_completed_deal:
            async with await db.client.start_session() as session:
                async with session.start_transaction():
                    updated_visit = await site_visit_repo.update_site_visit_status(
                        visit_id=id,
                        status=update_data.status.value if update_data.status else None,
                        notes=update_data.notes,
                        visit_fee=update_data.visit_fee,
                        fee_collected=update_data.fee_collected,
                        collected_by=update_data.collected_by,
                        visit_result=update_data.visit_result,
                        deal_closed=update_data.deal_closed,
                        session=session
                    )
                    if not updated_visit:
                        raise HTTPException(status_code=404, detail="Site visit not found")
                    
                    lead_id = updated_visit.get("lead_id")
                    property_id = updated_visit.get("property_id")
                    
                    # Cascade update lead to CLOSED
                    await db.client.nph_core.leads.update_one(
                        {"id": lead_id},
                        {"$set": {"status": "CLOSED"}},
                        session=session
                    )
                    
                    # Cascade update property to ARCHIVED
                    await db.client.nph_core.properties.update_one(
                        {"property_id": property_id},
                        {"$set": {"status": "ARCHIVED", "availability_status": "ARCHIVED"}},
                        session=session
                    )
                    try:
                        from bson import ObjectId
                        await db.client.nph_core.properties.update_one(
                            {"_id": ObjectId(property_id)},
                            {"$set": {"status": "ARCHIVED", "availability_status": "ARCHIVED"}},
                            session=session
                        )
                    except Exception:
                        pass
        else:
            updated_visit = await site_visit_repo.update_site_visit_status(
                visit_id=id,
                status=update_data.status.value if update_data.status else None,
                notes=update_data.notes,
                visit_fee=update_data.visit_fee,
                fee_collected=update_data.fee_collected,
                collected_by=update_data.collected_by,
                visit_result=update_data.visit_result,
                deal_closed=update_data.deal_closed
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
