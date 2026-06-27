# services/matching/engine.py
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone

def calculate_base_structural_match_score(prop: Dict[str, Any], reqs: Dict[str, Any]) -> int:
    """Calculates base structural match score up to 130 points."""
    score = 0
    # 1. Area Match Analysis (Weight: 40 Points)
    prop_area = prop.get("area", "").lower().strip()
    lead_area = reqs.get("area")
    if not lead_area and reqs.get("preferred_locations"):
        pref_locs = reqs.get("preferred_locations")
        lead_area = pref_locs[0] if pref_locs else None
    
    if lead_area and prop_area == lead_area.lower().strip():
        score += 40
        
    # 2. Budget Bounds Analysis (Weight: 30 Points)
    prop_price = prop.get("price", 0)
    max_budget = reqs.get("max_price") or reqs.get("budget_max") or 999999999
    min_budget = reqs.get("min_price") or 0
    if min_budget <= prop_price <= max_budget:
        score += 30
        
    # 3. Structural BHK Analysis (Weight: 20 Points)
    prop_bhk = prop.get("bhk", 0)
    lead_bhk = reqs.get("bhk", 0)
    if prop_bhk == lead_bhk:
        score += 20
        
    # 4. Amenities Parking Pass (Weight: 10 Points)
    if prop.get("parking") == reqs.get("parking", False):
        score += 10
        
    # 5. Ownership Type Bonus (Weight: 30 Points)
    ownership = prop.get("ownership_type", "broker")
    if ownership == "owner":
        score += 30
    elif ownership == "verified_broker":
        score += 15

    return score

def calculate_dynamic_property_confidence(prop: Dict[str, Any]) -> int:
    """Calculates property confidence score starting at base confidence with aging penalty applied."""
    base_confidence = prop.get("confidence_score", 100)
    last_verified = prop.get("last_verified_at")
    if last_verified:
        if last_verified.tzinfo is None:
            last_verified = last_verified.replace(tzinfo=timezone.utc)
        days_since = (datetime.now(timezone.utc) - last_verified).days
        aging_penalty = max(0, days_since) * 5
        return max(0, base_confidence - aging_penalty)
    return max(0, base_confidence)

async def get_broker_reliability_score(broker_phone: Optional[str]) -> int:
    """Retrieves broker's reliability score from db, defaulting to 100."""
    if not broker_phone:
        return 100
    from shared.utils.database import db
    if db.client is None:
        return 100
    broker = await db.client.nph_core.broker_profiles.find_one({"_id": broker_phone})
    if broker:
        return max(0, broker.get("reliability_score", 100))
    return 100

def calculate_match_score(property_data: Dict[str, Any], lead_budget_max: int) -> int:
    """Calculates a 0-100% confidence score for a property match (Legacy implementation)."""
    score = 50 # Base score for hitting the hard database filters (BHK, Area)

    # 1. Freshness Score (Max 20 points)
    updated_at = property_data.get("updated_at")
    if updated_at:
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=timezone.utc)
        days_old = (datetime.now(timezone.utc) - updated_at).days
        freshness_pts = max(0, 20 - (days_old * 2))
        score += freshness_pts
    else:
        score += 10 # Fallback for legacy data

    # 2. Budget Proximity Score (Max 30 points)
    price = property_data.get("price", 0)
    if lead_budget_max and price > 0:
        price_ratio = price / lead_budget_max
        if 0.85 <= price_ratio <= 1.0:
            score += 30  # Perfect budget fit
        elif 0.60 <= price_ratio < 0.85:
            score += 15  # Good deal, but might lack premium features
        elif price_ratio < 0.60:
            score += 0   # Too cheap, likely a quality mismatch
    else:
        score += 15 # Fallback

    return min(score, 100) # Cap at 100%

async def find_matches_for_lead(lead_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Queries inventory, scores matches, and returns the Top 3 based on composite trusted rank."""
    from apps.api.repositories.property_repository import property_repo

    bhk = lead_data.get("bhk")
    preferred_locations = lead_data.get("preferred_locations", [])
    if not preferred_locations and lead_data.get("area"):
        preferred_locations = [lead_data.get("area")]
    listing_type = lead_data.get("listing_type", "rent").lower()
    
    query_filter: Dict[str, Any] = {
        "status": "ACTIVE",
        "listing_type": listing_type
    }
    
    if bhk:
        query_filter["bhk"] = bhk
    if preferred_locations:
        query_filter["area"] = {"$regex": preferred_locations[0], "$options": "i"}

    try:
        raw_matches = await property_repo.find_filtered(query_filter=query_filter, limit=100)
        
        scored_matches = []
        for prop in raw_matches:
            broker_phone = prop.get("broker_phone")
            broker_reliability = 100
            is_verified = False
            
            if broker_phone:
                from shared.utils.database import db
                if db.client is not None:
                    broker = await db.client.nph_core.broker_profiles.find_one({"_id": broker_phone})
                    if broker:
                        broker_reliability = max(0, broker.get("reliability_score", 100))
                        is_verified = broker.get("verified", False)
            
            # Create copy to avoid mutating cache / raw documents
            prop_scored = dict(prop)
            if is_verified and prop_scored.get("ownership_type", "broker") == "broker":
                prop_scored["ownership_type"] = "verified_broker"
                
            structural_score = calculate_base_structural_match_score(prop_scored, lead_data)
            prop_confidence = calculate_dynamic_property_confidence(prop_scored)
            
            composite_score = structural_score + prop_confidence + broker_reliability
            prop_scored["match_score"] = composite_score
            scored_matches.append(prop_scored)
            
        scored_matches.sort(key=lambda x: x["match_score"], reverse=True)
        return scored_matches[:3]

    except Exception as e:
        print(f"[Matching Engine Error] Failed to pull inventory: {str(e)}")
        return []

def mask_property_for_client(property_data: Dict[str, Any]) -> Dict[str, Any]:
    """THE COMMISSION SHIELD + MATCH SCORE EXPORT"""
    masked = {
        "title": property_data.get("title"),
        "bhk": property_data.get("bhk"),
        "price": property_data.get("price"),
        "deposit": property_data.get("rental_details", {}).get("deposit"),
        "furnishing": property_data.get("rental_details", {}).get("furnishing"),
        "tenant_preference": property_data.get("rental_details", {}).get("preferred_tenant"),
        "general_area": property_data.get("area"),
        "match_score": property_data.get("match_score", 85) 
    }
    return masked