# apps/api/repositories/broker_repository.py
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from pymongo import ReturnDocument
from shared.utils.normalization import clean_phone

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
        # Note: Primary key _id stores the phone number and has a unique immutable index by default.
        # Removed redundant secondary index on 'phone'.
        pass

    async def upsert_broker(self, phone: str, name: str, company: Optional[str] = None) -> Dict[str, Any]:
        """Performs a standard registration/lookup of a broker profile."""
        cleaned = clean_phone(phone)
        if cleaned and phone.startswith("+91") and not cleaned.startswith("+91"):
            phone = f"+91{cleaned}"
        elif cleaned:
            phone = cleaned

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
                    "reliability_score": 100,
                    "verified": False
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
        cleaned = clean_phone(phone)
        if cleaned and phone.startswith("+91") and not cleaned.startswith("+91"):
            phone = f"+91{cleaned}"
        elif cleaned:
            phone = cleaned

        set_on_insert = {
            "name": f"Broker {phone}",
            "properties_posted": 0,
            "verified_properties": 0,
            "expired_properties": 0,
            "reliability_score": 100,
            "verified": False
        }
        # Prevent MongoDB ConflictingUpdateOperators error (Code 40)
        # by removing the field being incremented from $setOnInsert
        if field_to_increment in set_on_insert:
            del set_on_insert[field_to_increment]

        # Execute atomic increment and upsert in a single round trip
        result = await self.collection.find_one_and_update(
            {"_id": phone},
            {
                "$inc": {field_to_increment: 1},
                "$set": {"last_seen_at": datetime.now(timezone.utc), "phone": phone},
                "$setOnInsert": set_on_insert
            },
            upsert=True,
            return_document=ReturnDocument.AFTER
        )
        if not result:
            return None

        # Recalculate reliability score: (verified_properties / properties_posted) * 100
        verified = result.get("verified_properties", 0)
        posted = result.get("properties_posted", 0)
        
        divisor = posted if posted > 0 else 1
        reliability_score = max(0, int((verified / divisor) * 100))

        if reliability_score == result.get("reliability_score"):
            if "_id" in result:
                result["_id"] = str(result["_id"])
            return result

        # Store updated reliability score with optimistic concurrency control
        final_result = await self.collection.find_one_and_update(
            {
                "_id": phone,
                "properties_posted": posted,
                "verified_properties": verified
            },
            {"$set": {"reliability_score": reliability_score}},
            return_document=ReturnDocument.AFTER
        )
        if not final_result:
            final_result = await self.collection.find_one({"_id": phone})
            
        if final_result and "_id" in final_result:
            final_result["_id"] = str(final_result["_id"])
        return final_result

broker_repo = BrokerRepository()
