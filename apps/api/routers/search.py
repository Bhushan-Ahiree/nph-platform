# apps/api/routers/search.py
from fastapi import APIRouter, Depends, Query
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
import re
from shared.utils.database import get_db_client
from shared.utils.auth_guard import get_current_user_role
from services.property.commission_shield import shield_property
from apps.api.schemas.property_schema_v2 import PropertyPublicResponse, PropertyInternalResponse
from typing import Union

router = APIRouter(prefix="/properties", tags=["Search Operations"])

@router.get("/search", response_model=List[Union[PropertyInternalResponse, PropertyPublicResponse]])
async def search_properties(
    area: str = Query(..., description="Target locality sector"),
    bhk: int = Query(..., description="BHK count limit"),
    listing_type: str = Query(..., description="'rent' or 'sale'"),
    max_price: Optional[int] = Query(None, description="Upper nominal budget ceiling"),
    role: str = Depends(get_current_user_role),
    db: Any = Depends(get_db_client)
) -> Union[List[PropertyInternalResponse], List[PropertyPublicResponse]]:
    """
    Executes a high-performance search pipeline combining baseline filtering constraints 
    with zero-clamped confidence scores and dynamic broker reliability indices.
    """
    properties_collection = db["properties"]
    
    # Stage 1: Build the primary matching filters
    match_filter: Dict[str, Any] = {
        "status": "ACTIVE",
        "availability_status": "VERIFIED",
        "bhk": bhk,
        "listing_type": listing_type,
        "area": {"$regex": re.escape(area), "$options": "i"}
    }
    if max_price is not None:
        match_filter["price"] = {"$lte": max_price}
        
    # Stage 2: Execute native PyMongo Aggregation Pipeline
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
        {
            "$addFields": {
                "broker_profile": {"$arrayElemAt": ["$broker_info", 0]}
            }
        },
        {
            "$addFields": {
                "broker_reliability": {"$ifNull": ["$broker_profile.reliability_score", 100]},
                "now": datetime.now(timezone.utc)
            }
        },
        {
            "$addFields": {
                "days_since": {
                    "$divide": [
                        {"$subtract": ["$now", {"$ifNull": ["$last_verified_at", "$now"]}]},
                        1000 * 60 * 60 * 24
                    ]
                }
            }
        },
        {
            "$addFields": {
                "aging_penalty": {"$multiply": [{"$floor": "$days_since"}, 5]}
            }
        },
        {
            "$addFields": {
                "computed_confidence": {"$subtract": ["$confidence_score", "$aging_penalty"]}
            }
        },
        {
            "$addFields": {
                "clamped_confidence": {"$cond": {"if": {"$gt": ["$computed_confidence", 0]}, "then": "$computed_confidence", "else": 0}},
                "structural_score": 100
            }
        },
        {
            "$addFields": {
                "ownership_boost": {
                    "$switch": {
                        "branches": [
                            {"case": {"$eq": ["$ownership_type", "owner"]}, "then": 30},
                            {"case": {"$eq": ["$ownership_type", "verified_broker"]}, "then": 15},
                            {"case": {"$eq": ["$broker_profile.verified", True]}, "then": 15}
                        ],
                        "default": 0
                    }
                }
            }
        },
        {
            "$addFields": {
                "composite_score": {"$add": ["$structural_score", "$clamped_confidence", "$broker_reliability", "$ownership_boost"]}
            }
        },
        {"$sort": {"composite_score": -1}},
        {"$limit": 5}
    ]
    
    cursor = properties_collection.aggregate(pipeline)
    results = await cursor.to_list(length=5)
    
    shielded_results = []
    for item in results:
        # Dynamic calculation of matching justifications
        reasons = ["Structural Parameter Match"]
        if item.get("clamped_confidence", 100) >= 80:
            reasons.append("Freshly Verified Asset")
        if item.get("broker_reliability", 100) >= 90:
            reasons.append("Highly Trusted Source")
        item["match_reason"] = reasons
        
        # Serialize through role-based access controller
        shielded = shield_property(item, role=role)
        if role == "PUBLIC":
            shielded_results.append(PropertyPublicResponse.model_validate(shielded))
        else:
            shielded_results.append(PropertyInternalResponse.model_validate(shielded))
        
    return shielded_results