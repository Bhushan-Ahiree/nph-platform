# apps/api/routes/property.py
from typing import List
from shared.schemas.property import PropertyCreate, PropertyDB
from shared.utils.database import db
import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, status, Depends  # ADDED: Depends

# NEW IMPORT: Pull down the authentication guard dependency
from shared.utils.auth_guard import get_current_user

router = APIRouter(prefix="/properties", tags=["Properties"])

@router.get("/", response_model=list[PropertyDB])
async def get_properties(skip: int = 0, limit: int = 50):
    """PUBLIC ENDPOINT: Anyone can read listings without logging in."""
    cursor = db.client.nph_core.properties.find().skip(skip).limit(limit)
    properties = await cursor.to_list(length=limit)
    for prop in properties:
        prop["_id"] = str(prop["_id"])
    return properties


@router.post("/", response_model=PropertyDB, status_code=status.HTTP_201_CREATED)
async def create_property(
    property_in: PropertyCreate, 
    current_user: dict = Depends(get_current_user)  # LOCKED: Requires valid token
):
    """SECURE ENDPOINT: Inserts a new validated property into MongoDB."""
    property_dict = property_in.model_dump()
    
    existing_property = await db.client.nph_core.properties.find_one({
        "title": property_dict["title"],
        "location.city": property_dict["location"]["city"],
        "location.locality": property_dict["location"]["locality"]
    })
    if existing_property:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A property listing with this title and location already exists."
        )
    
    property_dict["property_id"] = f"prop_{uuid.uuid4().hex[:8]}"
    property_dict["created_at"] = datetime.now(timezone.utc)
    property_dict["updated_at"] = datetime.now(timezone.utc)
    
    # Track who posted this property inside the database record!
    property_dict["posted_by_user_id"] = current_user["id"]
    
    result = await db.client.nph_core.properties.insert_one(property_dict)
    created_property = await db.client.nph_core.properties.find_one({"_id": result.inserted_id})
    created_property["_id"] = str(created_property["_id"])
    return created_property


@router.patch("/{property_id}", response_model=PropertyDB)
async def update_property(
    property_id: str, 
    updates: dict, 
    current_user: dict = Depends(get_current_user)  # LOCKED: Requires valid token
):
    """SECURE ENDPOINT: Updates specific fields of an existing property."""
    banned_updates = ["_id", "id", "property_id", "created_at", "posted_by_user_id"]
    for field in banned_updates:
        updates.pop(field, None)
        
    if not updates:
        raise HTTPException(status_code=400, detail="No valid fields provided.")
        
    updates["updated_at"] = datetime.now(timezone.utc)
    
    result = await db.client.nph_core.properties.find_one_and_update(
        {"property_id": property_id},
        {"$set": updates},
        return_document=True
    )
    if not result:
        raise HTTPException(status_code=404, detail="Property not found.")
        
    result["_id"] = str(result["_id"])
    return result


@router.delete("/{property_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_property(
    property_id: str, 
    current_user: dict = Depends(get_current_user)  # LOCKED: Requires valid token
):
    """SECURE ENDPOINT: Hard deletes a property record from the cluster."""
    result = await db.client.nph_core.properties.delete_one({"property_id": property_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Property not found.")
    return None