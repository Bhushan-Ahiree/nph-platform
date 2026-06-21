# apps/api/repositories/broker_repository.py
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from pymongo import ReturnDocument

class BrokerRepository:
    """Isolates all physical database operations for the broker_profiles collection."""

    @property
    def collection(self):
        """Dynamically fetches the active collection pool via shared database singleton."""
        from shared.utils.database import db
        if db.client is None:
            raise RuntimeError("Database client is not initialized yet.")
        return db.client.nph_core.broker_profiles

    async def create_indexes(self):
        """Builds background unique indexing models for broker profiles."""
        await self.collection.create_index("phone", unique=True, sparse=True)

    async def upsert_broker(self, phone: str, name: str, company: Optional[str] = None) -> Dict[str, Any]:
        """Performs a standard registration/lookup of a broker profile."""
        update_data = {
            "phone": phone,
            "name": name,
            "last_seen_at": datetime.now(timezone.utc)
        }
        if company is not None:
            update_data["company"] = company

        result = await self.collection.find_one_and_update(
            {"_id": phone},
            {
                "$set": update_data,
                "$setOnInsert": {
                    "properties_posted": 0,
                    "verified_properties": 0,
                    "expired_properties": 0,
                    "reliability_score": 100
                }
            },
            upsert=True,
            return_document=ReturnDocument.AFTER
        )
        if result and "_id" in result:
            result["_id"] = str(result["_id"])
        return result

    async def increment_property_counter(self, phone: str, field_to_increment: str) -> Optional[Dict[str, Any]]:
        """
        Increments a given metric ('properties_posted', 'verified_properties', 'expired_properties')
        for the specified broker's phone number and recalculates their reliability score.
        """
        # Ensure the broker profile exists in the system
        broker = await self.collection.find_one({"_id": phone})
        if not broker:
            await self.upsert_broker(phone=phone, name=f"Broker {phone}")

        # Execute the count increment
        result = await self.collection.find_one_and_update(
            {"_id": phone},
            {
                "$inc": {field_to_increment: 1},
                "$set": {"last_seen_at": datetime.now(timezone.utc)}
            },
            return_document=ReturnDocument.AFTER
        )
        if not result:
            return None

        # Recalculate reliability score: (verified_properties / properties_posted) * 100
        verified = result.get("verified_properties", 0)
        posted = result.get("properties_posted", 0)
        
        divisor = posted if posted > 0 else 1
        reliability_score = max(0, int((verified / divisor) * 100))

        # Store updated reliability score
        final_result = await self.collection.find_one_and_update(
            {"_id": phone},
            {"$set": {"reliability_score": reliability_score}},
            return_document=ReturnDocument.AFTER
        )
        if final_result and "_id" in final_result:
            final_result["_id"] = str(final_result["_id"])
        return final_result

broker_repo = BrokerRepository()
