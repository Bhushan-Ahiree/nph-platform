# apps/api/routes/property.py
from fastapi import APIRouter, HTTPException, status, Depends, Query
from typing import Optional, Any, Dict
import uuid
from datetime import datetime, timezone

from shared.schemas.property import PropertyCreate, PropertyDB
from shared.utils.auth_guard import get_current_user
from apps.api.repositories.property_repository import property_repo  # REPO CONVERSION

router = APIRouter(prefix="/properties", tags=["Properties"])

@router.get("/", response_model=list[PropertyDB])
async def get_properties(
    skip: int = 0, limit: int = 50,
    city: Optional[str] = Query(None), locality: Optional[str] = Query(None),
    bhk: Optional[int] = Query(None), property_type: Optional[str] = Query(None),
    min_price: Optional[float] = Query(None), max_price: Optional[float] = Query(None)
):
    # Dynamic query object generation stays local to route parameter collection
    mongo_query: Dict[str, Any] = {}
    if city:
        mongo_query["location.city"] = {"$regex": f"^{city}$", "$options": "i"}
    if locality:
        mongo_query["location.locality"] = {"$regex": locality, "$options": "i"}
    if bhk:
        mongo_query["configuration.bhk"] = bhk
    if property_type:
        mongo_query["property_type"] = {"$regex": f"^{property_type}$", "$options": "i"}
    if min_price is not None or max_price is not None:
        mongo_query["price"] = {}
        if min_price is not None:
            mongo_query["price"]["$gte"] = min_price
        if max_price is not None:
            mongo_query["price"]["$lte"] = max_price

    # Clean repository encapsulation execution
    return await property_repo.find_filtered(mongo_query, skip=skip, limit=limit)

@router.post("/", response_model=PropertyDB, status_code=status.HTTP_201_CREATED)
async def create_property(property_in: PropertyCreate, current_user: dict = Depends(get_current_user)):
    property_dict = property_in.model_dump()
    
    # Clean check via our repository layer abstraction helper
    duplicate = await property_repo.check_duplicate(
        property_dict["title"], property_dict["location"]["city"], property_dict["location"]["locality"]
    )
    if duplicate:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A property listing with this title and location already exists."
        )
    
    property_dict["property_id"] = f"prop_{uuid.uuid4().hex[:8]}"
    property_dict["created_at"] = datetime.now(timezone.utc)
    property_dict["updated_at"] = datetime.now(timezone.utc)
    property_dict["posted_by_user_id"] = current_user["id"]
    
    return await property_repo.create(property_dict)

@router.patch("/{property_id}", response_model=PropertyDB)
async def update_property(property_id: str, updates: dict, current_user: dict = Depends(get_current_user)):
    banned_updates = ["_id", "id", "property_id", "created_at", "posted_by_user_id"]
    for field in banned_updates:
        updates.pop(field, None)
        
    if not updates:
        raise HTTPException(status_code=400, detail="No valid fields provided.")
        
    updates["updated_at"] = datetime.now(timezone.utc)
    
    result = await property_repo.update(property_id, updates)
    if not result:
        raise HTTPException(status_code=404, detail="Property not found.")
    return result

@router.delete("/{property_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_property(property_id: str, current_user: dict = Depends(get_current_user)):
    success = await property_repo.delete(property_id)
    if not success:
        raise HTTPException(status_code=404, detail="Property not found.")
    return None