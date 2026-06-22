# apps/api/repositories/property_repository.py
import re
import uuid
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from pymongo import ReturnDocument


class PropertyRepository:
    """Isolates all structural database execution logic for inventory intelligence."""

    def get_collection(self):
        """Dynamically fetches the active collection pool during execution to avoid import race conditions."""
        from shared.utils.database import db
        if db.client is None:
            raise RuntimeError("Database client is not initialized yet.")
        return db.client.nph_core.properties

    async def create(self, property_data: Dict[str, Any]) -> Dict[str, Any]:
        """Inserts a new property document into the collection and returns it with a serialized _id."""
        collection = self.get_collection()
        await collection.insert_one(property_data)
        if "_id" in property_data:
            property_data["_id"] = str(property_data["_id"])
        
        # Increment broker's properties_posted count
        broker_phone = property_data.get("broker_phone")
        if broker_phone:
            from apps.api.repositories.broker_repository import broker_repo
            await broker_repo.increment_property_counter(broker_phone, "properties_posted")

        return property_data

    async def check_duplicate(self, title: str, city: str, area: str) -> Optional[Dict[str, Any]]:
        """Checks if a property with the same title, city, and area already exists in the collection."""
        collection = self.get_collection()
        return await collection.find_one({
            "title": {"$regex": f"^{re.escape(title)}$", "$options": "i"},
            "city": {"$regex": f"^{re.escape(city)}$", "$options": "i"},
            "area": {"$regex": f"^{re.escape(area)}$", "$options": "i"}
        })

    async def find_by_ingestion_hash(self, ingestion_hash: str) -> Optional[Dict[str, Any]]:
        """
        Structural deduplication lookup for the mass ingestion pipeline.

        Queries the 'properties' collection for an existing ACTIVE document bearing
        the specified SHA-256 ingestion_hash. The hash is constructed upstream from
        price + area + bhk + listing_type + broker_phone so it is structurally unique
        per broker-property combination.

        Returns the matching document if found (caller should DROP the candidate),
        or None if the hash is unique (caller should INSERT the new document).
        """
        collection = self.get_collection()
        return await collection.find_one({
            "ingestion_hash": ingestion_hash,
            "status": "ACTIVE"
        })

    async def update(self, property_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Applies a partial update to a property document and returns the updated result."""
        collection = self.get_collection()
        result = await collection.find_one_and_update(
            {"property_id": property_id},
            {"$set": updates},
            return_document=ReturnDocument.AFTER
        )
        if result and "_id" in result:
            result["_id"] = str(result["_id"])
        return result

    async def upsert_property(self, collection, property_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Intelligently inserts or updates a property to prevent broker spam duplicates.
        Increments the duplicate_count automatically if seen multiple times.
        Initializes the 'ingestion_hash' field if one is provided in property_data,
        enabling the SHA-256 structural deduplication pipeline added in P0.
        """
        # Ensure a unique property ID exists
        if "property_id" not in property_data:
            property_data["property_id"] = f"prop_{uuid.uuid4().hex[:8]}"

        # Force the updated timestamp to right now using timezone-aware UTC
        property_data["updated_at"] = datetime.now(timezone.utc)
        if "status" not in property_data:
            property_data["status"] = "ACTIVE"
        if "availability_status" not in property_data:
            property_data["availability_status"] = "verified"
        if "last_verified_at" not in property_data:
            property_data["last_verified_at"] = datetime.now(timezone.utc)
        if "verification_count" not in property_data:
            property_data["verification_count"] = 1
        if "confidence_score" not in property_data:
            property_data["confidence_score"] = 100
        # Initialise ingestion_hash to None if not explicitly provided; the mass
        # ingestion pipeline always supplies it, manual routes leave it absent.
        if "ingestion_hash" not in property_data:
            property_data["ingestion_hash"] = None
        if "broker_phone" not in property_data or not property_data["broker_phone"]:
            source = property_data.get("source")
            if isinstance(source, dict):
                property_data["broker_phone"] = source.get("broker_phone")

        # Detach 'intelligence' from the $set block to avoid ConflictingUpdateOperators
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

        if result:
            intelligence = result.get("intelligence", {})
            dup_count = intelligence.get("duplicate_count", 1)
            broker_phone = result.get("broker_phone")
            if dup_count == 1 and broker_phone:
                from apps.api.repositories.broker_repository import broker_repo
                await broker_repo.increment_property_counter(broker_phone, "properties_posted")

        return result

    async def append_source_entry(
        self,
        ingestion_hash: str,
        broker_phone: Optional[str],
        group_name: Optional[str],
    ) -> Optional[Dict[str, Any]]:
        """
        Sprint A: Cross-broker source append on deduplication collision.

        When the ingestion pipeline detects that a property with this ingestion_hash
        already exists in the 'ACTIVE' bucket, it calls this method instead of
        dropping the duplicate. The new broker/group observation is pushed onto the
        property's 'sources' array and the intelligence.duplicate_count is incremented.

        This preserves forwarding intelligence — the same flat in Indira Nagar being
        broadcast across 15 broker groups is now analytically visible, not invisible.

        Args:
            ingestion_hash: SHA-256 structural hash of the property listing.
            broker_phone:   Cleaned 10-digit phone number of the forwarding broker.
            group_name:     Human-readable WhatsApp group name.

        Returns:
            The updated property document, or None if no matching ACTIVE doc found.
        """
        from datetime import datetime, timezone
        collection = self.get_collection()

        new_source = {
            "broker_phone": broker_phone,
            "group_name": group_name,
            "seen_at": datetime.now(timezone.utc),
        }

        result = await collection.find_one_and_update(
            {"ingestion_hash": ingestion_hash, "status": "ACTIVE"},
            {
                "$push": {"sources": new_source},
                "$inc": {"intelligence.duplicate_count": 1},
                "$set": {"updated_at": datetime.now(timezone.utc)},
            },
            return_document=ReturnDocument.AFTER,
        )

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