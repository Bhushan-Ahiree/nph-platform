from fastapi import APIRouter, HTTPException, Depends
from apps.api.schemas.match_schemas import MatchResponse, MatchUpdate
from apps.api.repositories.match_repository import MatchRepository
from apps.api.repositories.lead_repository import LeadRepository
from shared.utils.database import db
from typing import List, Dict, Any, Union
from datetime import datetime, timezone
from shared.utils.database import get_db_client
from shared.utils.auth_guard import get_current_user_role, require_staff
from apps.api.schemas.property_schema_v2 import PropertyPublicResponse, PropertyInternalResponse
from services.property.commission_shield import shield_property

import re
from services.matching.engine import (
    calculate_base_structural_match_score,
    calculate_dynamic_property_confidence,
    get_broker_reliability_score
)

router = APIRouter(prefix="/matches", tags=["CRM Property Matching Engine"])

match_repo = MatchRepository()
lead_repo = LeadRepository()


@router.post("/trigger/{lead_id}", response_model=List[MatchResponse])
async def run_matching_engine_for_lead(lead_id: str, _staff: str = Depends(require_staff)):
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
async def get_calculated_lead_matches(lead_id: str, _staff: str = Depends(require_staff)):
    """Retrieves cached recommendation entries calculated during matching passes."""
    return await match_repo.get_matches_by_lead(lead_id)


@router.patch("/{match_id}", response_model=MatchResponse)
async def update_match_status_endpoint(match_id: str, payload: MatchUpdate, _staff: str = Depends(require_staff)):
    """Updates the status of a recommendation block (e.g. SENT -> VIEWED)."""
    updated = await match_repo.update_match_status(match_id, payload.status)
    if not updated:
        raise HTTPException(status_code=404, detail="Recommendation block not found.")
    return updated


@router.get("/lead/{lead_id}", response_model=List[Union[PropertyInternalResponse, PropertyPublicResponse]])
async def get_lead_aware_matches(
    lead_id: str,
    role: str = Depends(get_current_user_role),
    db: Any = Depends(get_db_client)
) -> Union[List[PropertyInternalResponse], List[PropertyPublicResponse]]:
    """
    Executes a lead-aware inventory look-up. Automatically scores active listings against
    stored lead configurations, persists recommendation blocks, and returns shielded variants.
    """
    leads_collection = db["leads"]
    properties_collection = db["properties"]
    
    # Fetch customer tracking profile
    lead = await leads_collection.find_one({"id": lead_id})
    if not lead:
        raise HTTPException(status_code=404, detail="Lead profile not found")
        
    reqs = lead.get("requirements", {})
    area = reqs.get("area")
    bhk = reqs.get("bhk")
    listing_type = reqs.get("listing_type")
    max_price = reqs.get("max_price")
    
    if not area or not bhk or not listing_type:
        return [] # Requirements incomplete, yield empty subset smoothly
        
    # Execute the weighted matching calculation pipeline
    match_filter: Dict[str, Any] = {
        "status": "ACTIVE",
        "availability_status": "VERIFIED",
        "bhk": int(bhk),
        "listing_type": listing_type,
        "area": {"$regex": area, "$options": "i"}
    }
    if max_price:
        match_filter["price"] = {"$lte": int(max_price)}
        
    pipeline = [
        {"$match": match_filter},
        {
            "$lookup": {
                "from": "broker_profiles",
                "localField": "broker_phone",
                "foreignField": "_id",
                "as": "broker_info"
            }
        },
        {"$addFields": {"broker_profile": {"$arrayElemAt": ["$broker_info", 0]}}},
        {
            "$addFields": {
                "broker_reliability": {"$ifNull": ["$broker_profile.reliability_score", 100]},
                "now": datetime.now(timezone.utc)
            }
        },
        {"$addFields": {"days_since": {"$divide": [{"$subtract": ["$now", {"$ifNull": ["$last_verified_at", "$now"]}]}, 1000 * 60 * 60 * 24]}}},
        {"$addFields": {"aging_penalty": {"$multiply": [{"$floor": "$days_since"}, 5]}}},
        {"$addFields": {"computed_confidence": {"$subtract": ["$confidence_score", "$aging_penalty"]}}},
        {
            "$addFields": {
                "clamped_confidence": {"$cond": {"if": {"$gt": ["$computed_confidence", 0]}, "then": "$computed_confidence", "else": 0}},
                "structural_score": 100
            }
        },
        {"$addFields": {"composite_score": {"$add": ["$structural_score", "$clamped_confidence", "$broker_reliability"]}}},
        {"$sort": {"composite_score": -1}},
        {"$limit": 3}
    ]
    
    cursor = properties_collection.aggregate(pipeline)
    matched_items = await cursor.to_list(length=3)
    output_records = []
    
    for prop in matched_items:
        prop_id = str(prop["_id"])
        
        # Determine tracking justifications
        reasons = ["Matches Lead Profile"]
        if prop.get("clamped_confidence", 100) >= 80:
            reasons.append("High Inventory Freshness")
        prop["match_reason"] = reasons
        
        # PERSIST RECOMMENDATION EVENT: Log transitions down the conversion pipeline
        from apps.api.repositories.recommendation_repository import insert_recommendation_event
        await insert_recommendation_event(
            lead_id=lead_id,
            property_id=prop_id,
            event="SENT",
            match_score=int(prop.get("composite_score", 200))
        )
        
        # Apply data serialization boundaries
        shielded = shield_property(prop, role=role)
        if role == "PUBLIC":
            output_records.append(PropertyPublicResponse.model_validate(shielded))
        else:
            output_records.append(PropertyInternalResponse.model_validate(shielded))
        
    return output_records