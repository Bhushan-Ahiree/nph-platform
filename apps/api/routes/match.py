# apps/api/routes/match.py
from fastapi import APIRouter, HTTPException, status
from apps.api.schemas.match_schemas import MatchResponse, MatchUpdate
from apps.api.repositories.match_repository import MatchRepository
from apps.api.repositories.lead_repository import LeadRepository
from shared.utils.database import db
from typing import List

router = APIRouter(prefix="/matches", tags=["CRM Property Matching Engine"])
import re
from services.matching.engine import (
    calculate_base_structural_match_score,
    calculate_dynamic_property_confidence,
    get_broker_reliability_score
)

match_repo = MatchRepository()
lead_repo = LeadRepository()


@router.post("/trigger/{lead_id}", response_model=List[MatchResponse])
async def run_matching_engine_for_lead(lead_id: str):
    """Evaluates inventory properties against lead parameters using deterministic weighted logic."""
    lead = await lead_repo.get_lead_by_id(lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail=f"Lead profiles matching '{lead_id}' do not exist.")

    if db.client is None:
        raise HTTPException(status_code=500, detail="Database client is not initialized.")
    properties_col = db.client["nph_core"]["properties"]

    reqs = lead.get("requirements", {})
    # Baseline constraints check: 'area', 'bhk', 'listing_type'
    query_filter = {
        "status": "ACTIVE",
        "listing_type": reqs.get("listing_type", "rent")
    }
    if reqs.get("area"):
        query_filter["area"] = {"$regex": f"^{re.escape(reqs['area'])}$", "$options": "i"}
    if reqs.get("bhk"):
        query_filter["bhk"] = reqs["bhk"]

    cursor = properties_col.find(query_filter)
    properties = await cursor.to_list(length=200)

    # Get historical matches
    historical_matches = await match_repo.get_matches_by_lead(lead_id)
    sent_property_ids = set()
    for hm in historical_matches:
        sent_property_ids.update(hm.get("property_ids", []))

    candidate_scores = []

    for prop in properties:
        prop_id = prop.get("property_id")
        if not prop_id or prop_id in sent_property_ids:
            continue

        # Calculate structural match score
        structural_score = calculate_base_structural_match_score(prop, reqs)
        
        # Calculate dynamic property confidence score
        prop_confidence = calculate_dynamic_property_confidence(prop)
        
        # Calculate broker reliability score
        broker_phone = prop.get("broker_phone")
        broker_reliability = await get_broker_reliability_score(broker_phone)

        # Composite score
        composite_score = structural_score + prop_confidence + broker_reliability
        candidate_scores.append((prop_id, composite_score))

    # Sort descending by composite score
    candidate_scores.sort(key=lambda x: x[1], reverse=True)
    top_property_ids = [pid for pid, score in candidate_scores[:3]]

    if top_property_ids:
        await match_repo.insert_match(
            lead_id=lead_id,
            property_ids=top_property_ids,
            status="SENT"
        )

    return await match_repo.get_matches_by_lead(lead_id)


@router.get("/{lead_id}", response_model=List[MatchResponse])
async def get_calculated_lead_matches(lead_id: str):
    """Retrieves cached recommendation entries calculated during matching passes."""
    return await match_repo.get_matches_by_lead(lead_id)


@router.patch("/{match_id}", response_model=MatchResponse)
async def update_match_status_endpoint(match_id: str, payload: MatchUpdate):
    """Updates the status of a recommendation block (e.g. SENT -> VIEWED)."""
    updated = await match_repo.update_match_status(match_id, payload.status)
    if not updated:
        raise HTTPException(status_code=404, detail="Recommendation block not found.")
    return updated