# apps/api/repositories/match_repository.py
import uuid
from datetime import datetime, timezone
from typing import List, Optional
from pymongo import ReturnDocument


class MatchRepository:
    """Manages match computation result persistence and retrieval."""

    @property
    def collection(self):
        """Dynamically fetches the active collection pool via shared database singleton."""
        from shared.utils.database import db
        if db.client is None:
            raise RuntimeError("Database client is not initialized yet.")
        return db.client.nph_core.matches

    async def create_indexes(self):
        """Builds background indexing models for lead queries."""
        await self.collection.create_index([("lead_id", 1), ("generated_at", -1)])
        await self.collection.create_index("match_id", unique=True)
        await self.collection.create_index("lead_id")
        await self.collection.create_index("generated_at")

    async def insert_match(self, lead_id: str, property_ids: List[str], status: str = "SENT") -> dict:
        """Writes a new recommendation block to MongoDB."""
        payload = {
            "match_id": f"match_{uuid.uuid4().hex[:8]}",
            "lead_id": lead_id,
            "property_ids": property_ids,
            "status": status,
            "generated_at": datetime.now(timezone.utc)
        }
        await self.collection.insert_one(payload)
        return payload

    async def get_matches_by_lead(self, lead_id: str) -> List[dict]:
        """Retrieves all historical matches presented to a specific phone number, sorted by generated_at descending."""
        cursor = self.collection.find({"lead_id": lead_id}).sort("generated_at", -1)
        matches = await cursor.to_list(length=100)
        return matches

    async def update_match_status(self, match_id: str, status: str) -> Optional[dict]:
        """Patches the status when a user views or archives an offer."""
        result = await self.collection.find_one_and_update(
            {"match_id": match_id},
            {"$set": {"status": status}},
            return_document=ReturnDocument.AFTER
        )
        return result