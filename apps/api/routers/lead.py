# apps/api/routers/lead.py
from fastapi import APIRouter, HTTPException, status
from apps.api.schemas.lead_schemas import LeadCreate, LeadUpdate, LeadResponse
from apps.api.repositories.lead_repository import LeadRepository  # FIXED IMPORT PATH
from typing import List

router = APIRouter(prefix="/leads", tags=["CRM Lead Management"])
repo = LeadRepository()

@router.on_event("startup")
async def ensure_repository_indexes():
    await repo.create_indexes()

@router.post("", response_model=LeadResponse, status_code=status.HTTP_201_CREATED)
async def create_new_lead(payload: LeadCreate):
    """Parses customer demand criteria, validates input logic, and stores inside Atlas."""
    try:
        return await repo.insert_lead(payload)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to ingest lead schema: {str(e)}")

@router.get("", response_model=List[LeadResponse])
async def list_all_leads(limit: int = 100, skip: int = 0):
    return await repo.get_all_leads(limit=limit, skip=skip)

@router.get("/{lead_id}", response_model=LeadResponse)
async def get_lead_by_unique_identifier(lead_id: str):
    lead = await repo.get_lead_by_id(lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail=f"Lead record matching '{lead_id}' not found.")
    return lead

@router.patch("/{lead_id}", response_model=LeadResponse)
async def modify_lead_records(lead_id: str, payload: LeadUpdate):
    lead = await repo.get_lead_by_id(lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail=f"Lead record matching '{lead_id}' not found.")
    return await repo.update_lead(lead_id, payload)

@router.delete("/{lead_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_lead_permanently(lead_id: str):
    lead = await repo.get_lead_by_id(lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail=f"Lead record matching '{lead_id}' not found.")
    await repo.delete_lead(lead_id)
    return None