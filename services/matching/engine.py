# services/matching/engine.py
from typing import Dict, Any, List
from datetime import datetime, timezone

def calculate_match_score(property_data: Dict[str, Any], lead_budget_max: int) -> int:
    """Calculates a 0-100% confidence score for a property match."""
    score = 50 # Base score for hitting the hard database filters (BHK, Area)

    # 1. Freshness Score (Max 20 points)
    # 0 days old = 20 pts, 10 days old = 0 pts
    updated_at = property_data.get("updated_at")
    if updated_at:
        # Handle potential missing timezone info by forcing UTC
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
    """Queries inventory, scores the matches, and returns the Top 3."""
    from apps.api.repositories.property_repository import property_repo

    bhk = lead_data.get("bhk")
    budget_max = lead_data.get("budget_max")
    preferred_locations = lead_data.get("preferred_locations", [])
    
    query_filter: Dict[str, Any] = {"availability.status": "active"}
    
    if bhk: query_filter["bhk"] = bhk
    if budget_max: query_filter["price"] = {"$lte": budget_max}
    if preferred_locations:
        query_filter["area"] = {"$regex": preferred_locations[0], "$options": "i"}

    try:
        # Fetch Top 10 broad matches instead of 3, so we can rank them
        raw_matches = await property_repo.find_filtered(query_filter=query_filter, limit=10)
        
        # Score and Sort
        scored_matches = []
        for match in raw_matches:
            score = calculate_match_score(match, budget_max)
            match["match_score"] = score
            scored_matches.append(match)
            
        # Sort descending by score and slice the Top 3 absolute best
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
        # Export the score so we can brag about it to the client!
        "match_score": property_data.get("match_score", 85) 
    }
    return masked