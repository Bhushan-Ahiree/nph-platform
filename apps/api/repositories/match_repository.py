# apps/api/repositories/match_repository.py
from motor.motor_asyncio import AsyncIOMotorClient
from apps.api.schemas.match_schemas import MatchResponse
from datetime import datetime
from typing import List
import os
import uuid

class MatchRepository:
    def __init__(self):
        self.mongo_url = os.getenv("MONGO_URL") or os.getenv("MONGO_URI")
        self.client = AsyncIOMotorClient(self.mongo_url)
        self.db = self.client["nph_core"]
        self.collection = self.db["matches"]

    async def create_indexes(self):
        """Builds composite querying structures for sorting match profiles."""
        await self.collection.create_index([("lead_id", 1), ("property_id", 1)], unique=True)
        await self.collection.create_index([("lead_id", 1), ("score", -1)])

    async def save_match(self, lead_id: str, property_id: str, score: int, reasons: List[str]) -> dict:
        """Upserts a computed profile score matrix to avoid duplicate match tracking records."""
        match_id = f"match_{uuid.uuid4().hex[:8]}"
        now = datetime.utcnow()

        payload = {
            "lead_id": lead_id,
            "property_id": property_id,
            "score": score,
            "reasons": reasons,
            "updated_at": now
        }

        # If a score record exists for this specific combination, update it; otherwise insert fresh
        await self.collection.update_one(
            {"lead_id": lead_id, "property_id": property_id},
            {
                "$set": payload,
                "$setOnInsert": {"match_id": match_id, "sent": False, "viewed": False, "shortlisted": False, "site_visit_requested": False, "created_at": now}
            },
            upsert=True
        )

        return await self.collection.find_one({"lead_id": lead_id, "property_id": property_id}, {"_id": 0})

    async def get_matches_for_lead(self, lead_id: str, min_score: int = 50) -> List[dict]:
        cursor = self.collection.find(
            {"lead_id": lead_id, "score": {"$gte": min_score}}, 
            {"_id": 0}
        ).sort("score", -1)
        return await cursor.to_list(length=50)