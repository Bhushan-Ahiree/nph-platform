# apps/api/routes/property.py
from fastapi import APIRouter, HTTPException, status
from typing import List
from shared.schemas.property import PropertyCreate, PropertyDB
from shared.utils.database import db
import uuid
from datetime import datetime, timezone

# This router groups all /properties endpoints together
router = APIRouter(prefix="/properties", tags=["Properties"])

@router.post("/", response_model=PropertyDB, status_code=status.HTTP_201_CREATED)
async def create_property(property_in: PropertyCreate):
    """Inserts a new validated property into MongoDB, protecting against duplicates."""
    
    # 1. Convert the Pydantic model into a Python dictionary
    property_dict = property_in.model_dump()
    
    # 2. DUPLICATE CHECK: Look for an existing property with the same title and location
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
    
    # 3. Inject internal tracking fields if it's unique
    property_dict["property_id"] = f"prop_{uuid.uuid4().hex[:8]}"
    property_dict["created_at"] = datetime.now(timezone.utc)
    property_dict["updated_at"] = datetime.now(timezone.utc)
    
    # 4. Insert into the database
    result = await db.client.nph_core.properties.insert_one(property_dict)
    
    # 5. Fetch and return the fresh document
    created_property = await db.client.nph_core.properties.find_one({"_id": result.inserted_id})
    created_property["_id"] = str(created_property["_id"])
    
    return created_property

@router.get("/", response_model=List[PropertyDB])
async def list_properties(limit: int = 50, skip: int = 0):
    """Retrieves a list of properties with basic pagination."""
    
    # 1. Ask MongoDB to find properties, skip a certain amount, and limit the return size
    cursor = db.client.nph_core.properties.find().skip(skip).limit(limit)
    
    # 2. Await the cursor to fetch the actual list of documents
    properties = await cursor.to_list(length=limit)
    
    # 3. Convert ObjectIds to strings for every property in the list
    for prop in properties:
        prop["_id"] = str(prop["_id"])
        
    return properties


# apps/api/routes/property.py (Continued)

@router.patch("/{property_id}", response_model=PropertyDB)
async def update_property(property_id: str, updates: dict):
    """Updates specific fields of an existing property by its business property_id."""
    
    # 1. Prevent the client from altering internal structural tracking tokens
    banned_updates = ["_id", "id", "property_id", "created_at"]
    for field in banned_updates:
        updates.pop(field, None)
        
    if not updates:
        raise HTTPException(
            status_code=400, 
            detail="No valid fields provided for update."
        )
        
    # 2. Append an automated modification metadata timestamp
    updates["updated_at"] = datetime.now(timezone.utc)
    
    # 3. Request MongoDB to look up the document by our custom business property_id string
    # We use '$set' to update only the dirty fields passed in the request body
    result = await db.client.nph_core.properties.find_one_and_update(
        {"property_id": property_id},
        {"$set": updates},
        return_document=True # Returns the fresh document after modifications are applied
    )
    
    if not result:
        raise HTTPException(
            status_code=404, 
            detail=f"Property with ID {property_id} not found."
        )
        
    # 4. Cast the standard BSON ObjectId to string for browser interpretation
    result["_id"] = str(result["_id"])
    return result

@router.delete("/{property_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_property(property_id: str):
    """Hard deletes a property record completely from the cluster."""
    
    result = await db.client.nph_core.properties.delete_one({"property_id": property_id})
    
    # Check if a document was actually deleted
    if result.deleted_count == 0:
        raise HTTPException(
            status_code=404, 
            detail=f"Property with ID {property_id} not found."
        )
        
    # 204 Status code returns absolutely nothing in the response body on success
    return None