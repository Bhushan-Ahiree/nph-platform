# apps/api/routers/lead.py
from fastapi import APIRouter, HTTPException, status
from apps.api.schemas.lead_schemas import LeadCreate, LeadUpdate, LeadResponse
from apps.api.repositories.lead_repository import LeadRepository  # FIXED IMPORT PATH
from typing import List, Optional

router = APIRouter(prefix="/leads", tags=["CRM Lead Management"])
repo = LeadRepository()

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

@router.get("/queue")
async def get_lead_operations_queue(
    lead_type: Optional[str] = None,
    source: Optional[str] = None,
    status: Optional[str] = None
):
    from shared.utils.database import db
    
    match_query = {}
    if lead_type:
        match_query["lead_type"] = lead_type
    if source:
        match_query["source"] = source
    if status:
        match_query["status"] = status
        
    pipeline = [
        {"$match": match_query},
        {
            "$facet": {
                "hot": [
                    {"$match": {"lead_temperature": "HOT"}},
                    {"$sort": {"priority_score": -1, "created_at": -1}},
                    {"$project": {"_id": 0}}
                ],
                "warm": [
                    {"$match": {"lead_temperature": "WARM"}},
                    {"$sort": {"priority_score": -1, "created_at": -1}},
                    {"$project": {"_id": 0}}
                ],
                "cold": [
                    {"$match": {"lead_temperature": "COLD"}},
                    {"$sort": {"priority_score": -1, "created_at": -1}},
                    {"$project": {"_id": 0}}
                ],
                "total_count": [{"$count": "count"}]
            }
        }
    ]
    
    results = await db.client.nph_core.leads.aggregate(pipeline).to_list(1)
    if not results:
        return {"hot": [], "warm": [], "cold": [], "total": 0}
        
    facet_data = results[0]
    total = facet_data.get("total_count", [])
    total_val = total[0]["count"] if total else 0
    
    return {
        "hot": facet_data.get("hot", []),
        "warm": facet_data.get("warm", []),
        "cold": facet_data.get("cold", []),
        "total": total_val
    }

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