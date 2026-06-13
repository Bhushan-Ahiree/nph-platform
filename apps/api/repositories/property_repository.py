# apps/api/repositories/property_repository.py
import uuid
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from pymongo import ReturnDocument
from pymongo.collection import Collection

class PropertyRepository:
    """Isolates all structural database execution logic for inventory intelligence."""
    
    def get_collection(self):
        """Dynamically fetches the active collection pool during execution to avoid import race conditions."""
        from shared.utils.database import db  # <-- Lazy import at execution time!
        if db.client is None:
            raise RuntimeError("Database client is not initialized yet.")
        return db.client.nph_core.properties

    async def upsert_property(self, collection: Collection, property_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Intelligently inserts or updates a property to prevent broker spam duplicates.
        Increments the duplicate_count automatically if seen multiple times.
        """
        # Ensure a unique property ID exists
        if "property_id" not in property_data:
            property_data["property_id"] = f"prop_{uuid.uuid4().hex[:8]}"

        # Force the updated timestamp to right now using timezone-aware UTC
        property_data["updated_at"] = datetime.now(timezone.utc)

        # -------------------------------------------------------------
        # THE FIX: Completely detach 'intelligence' from the $set block
        # so MongoDB doesn't throw a ConflictingUpdateOperators error.
        # -------------------------------------------------------------
        if "intelligence" in property_data:
            del property_data["intelligence"]

        # Extract created_at so it is ONLY set when a new document is inserted
        created_at_val = property_data.pop("created_at", datetime.now(timezone.utc))
        
        # The Uniqueness Constraint: Are we seeing the same property from the same broker?
        filter_query = {
            "bhk": property_data.get("bhk"),
            "area": property_data.get("area"),
            "listing_type": property_data.get("listing_type"),
            "source.broker_name": property_data.get("source", {}).get("broker_name")
        }

        # The Operation: Update existing data and increment the spam/duplicate counter
        update_op = {
            "$set": property_data,
            "$inc": {"intelligence.duplicate_count": 1},
            "$setOnInsert": {
                "created_at": created_at_val,
                "intelligence.hot_property": False,
                "intelligence.source_confidence": 100
            }
        }

        # Execute the transaction
        result = await collection.find_one_and_update(
            filter_query,
            update_op,
            upsert=True,
            return_document=ReturnDocument.AFTER
        )

        # Cleanup ObjectId for clean JSON serialization out of the API
        if result and "_id" in result:
            result["_id"] = str(result["_id"])
            
        return result

    async def find_filtered(self, query_filter: Dict[str, Any], skip: int = 0, limit: int = 20) -> List[Dict[str, Any]]:
        """Used by the Search API and Matching Engine to pull valid inventory."""
        collection = self.get_collection()
        cursor = collection.find(query_filter).sort("updated_at", -1).skip(skip).limit(limit)
        properties = await cursor.to_list(length=limit)
        for prop in properties:
            prop["_id"] = str(prop["_id"])
        return properties

    async def delete(self, property_id: str) -> bool:
        collection = self.get_collection()
        result = await collection.delete_one({"property_id": property_id})
        return result.deleted_count > 0

property_repo = PropertyRepository()