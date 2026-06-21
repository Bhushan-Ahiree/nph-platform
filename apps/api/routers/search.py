# apps/api/routers/search.py
from fastapi import APIRouter, HTTPException, Query
from typing import Optional, Dict, Any
from apps.api.repositories.property_repository import property_repo

router = APIRouter(prefix="/properties", tags=["Inventory Search Engine"])

@router.get("/search")
async def search_inventory(
    bhk: Optional[int] = Query(None, description="Number of bedrooms"),
    area: Optional[str] = Query(None, description="Locality or area name"),
    max_price: Optional[int] = Query(None, description="Maximum budget (rent/price)"),
    furnishing: Optional[str] = Query(None, description="furnished, semi-furnished, or unfurnished"),
    preferred_tenant: Optional[str] = Query(None, description="family, bachelors, or any"),
    limit: int = Query(20, ge=1, le=50)
):
    """
    Dynamically queries the MongoDB inventory based on strict parameters.
    """
    query_filter: Dict[str, Any] = {}

    # 1. Exact Match Filters
    if bhk is not None:
        query_filter["bhk"] = bhk
    
    # 2. Case-Insensitive Text Filters (Handles variations like "indira nagar" vs "Indira Nagar")
    if area:
        query_filter["area"] = {"$regex": area, "$options": "i"}
        
    # 3. Numeric Range Filters
    if max_price:
        query_filter["price"] = {"$lte": max_price}
        
    # 4. Nested Object Filters (Looking inside the V2 Schema)
    if furnishing:
        query_filter["rental_details.furnishing"] = {"$regex": furnishing, "$options": "i"}
        
    if preferred_tenant:
        query_filter["rental_details.preferred_tenant"] = {"$regex": preferred_tenant, "$options": "i"}
        
    # Always ensure we only return active listings
    query_filter["status"] = "ACTIVE"

    try:
        # Hit the database using the repository method we already built!
        results = await property_repo.find_filtered(query_filter=query_filter, limit=limit)
        
        return {
            "status": "success",
            "count": len(results),
            "data": results
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Search Engine Error: {str(e)}")