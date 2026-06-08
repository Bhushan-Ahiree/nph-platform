# apps/api/routes/match.py
from fastapi import APIRouter, HTTPException, status
from apps.api.schemas.match_schemas import MatchResponse
from apps.api.repositories.match_repository import MatchRepository
from apps.api.repositories.lead_repository import LeadRepository
from motor.motor_asyncio import AsyncIOMotorClient
from typing import List
import os

router = APIRouter(prefix="/matches", tags=["CRM Property Matching Engine"])
match_repo = MatchRepository()
lead_repo = LeadRepository()

@router.post("/trigger/{lead_id}", response_model=List[MatchResponse])
async def run_matching_engine_for_lead(lead_id: str):
    """Evaluates inventory properties against lead parameters using deterministic weighted logic."""
    lead = await lead_repo.get_lead_by_id(lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail=f"Lead profiles matching '{lead_id}' do not exist.")

    # Grab the direct mongo client link to query properties instantly
    mongo_url = os.getenv("MONGO_URL") or os.getenv("MONGO_URI")
    client = AsyncIOMotorClient(mongo_url)
    properties_col = client["nph_core"]["properties"]

    # Pull active supply matching the core request transaction profile (e.g. rent vs buy)
    cursor = properties_col.find({"listing_type": lead["requirement_type"], "status": "active"})
    properties = await cursor.to_list(length=200)

    computed_matches = []

    for prop in properties:
        score = 0
        reasons = []

        # 1. Area Match Analysis (Weight: 40 Points)
        # Check if the property area matches any preferred areas from the lead
        prop_area = prop.get("location", {}).get("area", "")
        if prop_area in lead.get("preferred_areas", []):
            score += 40
            reasons.append("area_match")

        # 2. Budget Bounds Analysis (Weight: 30 Points)
        prop_price = prop.get("price", 0)
        if lead["budget_min"] <= prop_price <= lead["budget_max"]:
            score += 30
            reasons.append("budget_match")

        # 3. Structural BHK Analysis (Weight: 20 Points)
        prop_bhk = prop.get("configuration", {}).get("bhk", 0)
        lead_bhk = lead.get("configuration", {}).get("bhk", 0)
        if prop_bhk == lead_bhk:
            score += 20
            reasons.append("bhk_match")

        # 4. Amenities Parking Pass (Weight: 10 Points)
        if prop.get("parking") == lead.get("parking"):
            score += 10
            reasons.append("parking_match")

        # Ingestion Guard: Only log viable options above our 50-point threshold
        if score >= 50:
            saved = await match_repo.save_match(
                lead_id=lead_id,
                property_id=prop.get("property_id", str(prop.get("_id"))),
                score=score,
                reasons=reasons
            )
            computed_matches.append(saved)

    return await match_repo.get_matches_for_lead(lead_id)

@router.get("/{lead_id}", response_model=List[MatchResponse])
async def get_calculated_lead_matches(lead_id: str, min_score: int = 50):
    """Retrieves cached recommendation entries calculated during matching passes."""
    return await match_repo.get_matches_for_lead(lead_id, min_score=min_score)