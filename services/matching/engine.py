# services/matching/engine.py
from typing import Dict, Any, List

async def find_matches_for_lead(lead_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Takes an extracted Lead Profile and queries the inventory for the top 3 matches.
    """
    # -----------------------------------------------------------------
    # THE FIX: We moved this import inside the function!
    # Now the Celery worker won't crash when it boots up.
    # -----------------------------------------------------------------
    from apps.api.repositories.property_repository import property_repo

    # 1. Extract the core requirements from the Lead JSON
    bhk = lead_data.get("bhk")
    budget_max = lead_data.get("budget_max")
    preferred_locations = lead_data.get("preferred_locations", [])
    
    # 2. Build the dynamic database filter
    query_filter: Dict[str, Any] = {
        "availability.status": "active"
    }
    
    if bhk:
        query_filter["bhk"] = bhk
        
    if budget_max:
        query_filter["price"] = {"$lte": budget_max}
        
    if preferred_locations:
        primary_location = preferred_locations[0]
        query_filter["area"] = {"$regex": primary_location, "$options": "i"}

    # 3. Hit the database and limit to the Top 3 best matches
    try:
        matches = await property_repo.find_filtered(query_filter=query_filter, limit=3)
        return matches
    except Exception as e:
        print(f"[Matching Engine Error] Failed to pull inventory: {str(e)}")
        return []

def mask_property_for_client(property_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    THE COMMISSION SHIELD: Strips out broker details and exact locations 
    before sending the data back to the buyer via WhatsApp.
    """
    masked = {
        "title": property_data.get("title"),
        "bhk": property_data.get("bhk"),
        "price": property_data.get("price"),
        "deposit": property_data.get("rental_details", {}).get("deposit"),
        "furnishing": property_data.get("rental_details", {}).get("furnishing"),
        "tenant_preference": property_data.get("rental_details", {}).get("preferred_tenant"),
        "general_area": property_data.get("area")
    }
    return masked