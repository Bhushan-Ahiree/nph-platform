# apps/api/routers/inventory.py
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from services.property.extractor import extract_property_details
from apps.api.repositories.property_repository import property_repo
from apps.api.schemas.property_schema_v2 import PropertySchemaV2
from shared.utils.database import db  # Use your existing db utility

router = APIRouter(prefix="/inventory", tags=["Inventory Intelligence"])

class IngestRequest(BaseModel):
    raw_message: str

@router.post("/ingest")
async def ingest_property_message(request: IngestRequest):
    """
    Takes a raw broker message, uses Llama 3.2 to extract the intelligence,
    maps flat LLM keys into the nested V2 schema layout, and upserts it.
    """
    # Grab the active database collection safely at execution time
    if db.client is None:
        raise HTTPException(status_code=500, detail="Database client is not initialized.")
    properties_collection = db.client.nph_core.properties

    # 1. AI Extraction (Returns flat keys)
    flat_data = extract_property_details(request.raw_message)
    
    if not flat_data:
        raise HTTPException(status_code=400, detail="AI failed to extract property details.")
    
    # 2. Structural Normalization: Map flat LLM keys into nested V2 Schema blocks
    nested_data = {
        "title": flat_data.get("title", "Property Listing"),
        "description": flat_data.get("raw_message"),
        "property_type": flat_data.get("property_type", "apartment"),
        "listing_type": flat_data.get("listing_type", "rent"),
        "city": flat_data.get("city", "Nashik"),
        "area": flat_data.get("area", "Unknown Locality"),
        "price": flat_data.get("price", 0),
        "bhk": flat_data.get("bhk", 0),
        "parking": flat_data.get("parking", False),
        "raw_message": request.raw_message,
        
        # Nested Source Object
        "source": {
            "type": "broker_group",
            "group_name": "WhatsApp Intelligence Source",
            "broker_name": flat_data.get("broker_name"),
            "broker_phone": flat_data.get("broker_phone")
        },
        
        # Nested Rental Details Object
        "rental_details": {
            "deposit": flat_data.get("deposit", 0),
            "preferred_tenant": flat_data.get("preferred_tenant", "any"),
            "furnishing": flat_data.get("furnishing", "unfurnished")
        },
        
        # Nested Availability Object (Will auto-initialize via schema defaults)
        "availability": {
            "status": "active",
            "verified_by": "automated"
        }
    }
    
    # 3. Strict Schema Validation
    try:
        validated_property = PropertySchemaV2(**nested_data).model_dump()
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Data Normalization Failed: {str(e)}")
        
    # 4. Database Upsert
    result = await property_repo.upsert_property(properties_collection, validated_property)
    
    return {
        "status": "success",
        "action": "Inserted" if result.get("intelligence", {}).get("duplicate_count", 0) == 1 else "Updated",
        "duplicate_count": result.get("intelligence", {}).get("duplicate_count", 1),
        "data": result
    }