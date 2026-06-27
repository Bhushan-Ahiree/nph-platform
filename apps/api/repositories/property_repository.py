# apps/api/repositories/property_repository.py
import uuid
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
import re
from pymongo import ReturnDocument


from shared.utils.normalization import compute_ingestion_hash, clean_phone

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
        the specified SHA-256 ingestion_hash. The hash is derived from price + area
        + bhk + listing_type + broker_phone.

        Returns the matching document if found, or None if unique.
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
        Enforces unique SHA-256 ingestion_hash checks to prevent duplicate listings.
        On duplicate collision, appends a source tracking entry and increments duplicate count.
        """
        # Resolve broker phone and clean it to 10 digits
        broker_phone = property_data.get("broker_phone")
        if not broker_phone:
            source = property_data.get("source")
            if isinstance(source, dict):
                broker_phone = source.get("broker_phone")
        
        clean_phone_val = clean_phone(broker_phone)

        # Determine ingestion hash
        ingestion_hash = property_data.get("ingestion_hash")
        if not ingestion_hash:
            ingestion_hash = compute_ingestion_hash(
                price=property_data.get("price", 0),
                area=property_data.get("area", ""),
                bhk=property_data.get("bhk", 0),
                listing_type=property_data.get("listing_type", "rent"),
                broker_phone=clean_phone_val
            )
            property_data["ingestion_hash"] = ingestion_hash

        # Check for duplication on ACTIVE hash collision
        existing = await collection.find_one({
            "ingestion_hash": ingestion_hash,
            "status": "ACTIVE"
        })

        group_name = None
        source = property_data.get("source")
        if isinstance(source, dict):
            group_name = source.get("group_name")

        if existing:
            # Collision found — run collision workflow (append broker to sources array)
            result = await self.append_source_entry(
                ingestion_hash=ingestion_hash,
                broker_phone=clean_phone_val,
                group_name=group_name
            )
            return result

        # No collision — proceed to insert a new property document
        if "property_id" not in property_data:
            property_data["property_id"] = f"prop_{uuid.uuid4().hex[:8]}"

        property_data["created_at"] = property_data.get("created_at") or datetime.now(timezone.utc)
        property_data["updated_at"] = datetime.now(timezone.utc)
        property_data["status"] = "ACTIVE"
        
        if "availability_status" not in property_data:
            property_data["availability_status"] = "NEW"
        if "last_verified_at" not in property_data:
            property_data["last_verified_at"] = datetime.now(timezone.utc)
        if "verification_count" not in property_data:
            property_data["verification_count"] = 1
        if "confidence_score" not in property_data:
            property_data["confidence_score"] = 100

        # Initialize sources array
        if "sources" not in property_data or not property_data["sources"]:
            property_data["sources"] = [{
                "broker_phone": clean_phone_val,
                "group_name": group_name,
                "seen_at": datetime.now(timezone.utc)
            }]

        if "intelligence" not in property_data:
            property_data["intelligence"] = {
                "hot_property": False,
                "duplicate_count": 0,
                "source_confidence": 100
            }
        else:
            if isinstance(property_data["intelligence"], dict):
                property_data["intelligence"]["duplicate_count"] = 0

        await collection.insert_one(property_data)

        if "_id" in property_data:
            property_data["_id"] = str(property_data["_id"])

        if clean_phone_val:
            from apps.api.repositories.broker_repository import broker_repo
            await broker_repo.increment_property_counter(clean_phone_val, "properties_posted")

        return property_data

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