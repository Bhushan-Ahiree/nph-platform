# apps/api/repositories/recommendation_repository.py
from datetime import datetime, timezone
from bson import ObjectId
from typing import List, Optional

class RecommendationRepository:
    """Manages persistence for recommendation events within the conversion funnel."""

    @property
    def collection(self):
        """Dynamically fetches the recommendation events collection."""
        from shared.utils.database import db
        if db.client is None:
            raise RuntimeError("Database client is not initialized yet.")
        return db.client.nph_core.recommendation_events

    async def insert_recommendation_event(self, lead_id: str, property_id: str, event: str, match_score: int) -> dict:
        """Writes a new recommendation lifecycle event to the database."""
        payload = {
            "lead_id": lead_id,
            "property_id": property_id,
            "event": event,
            "match_score": match_score,
            "created_at": datetime.now(timezone.utc)
        }
        result = await self.collection.insert_one(payload)
        payload["id"] = str(result.inserted_id)
        if "_id" in payload:
            del payload["_id"]
        return payload

recommendation_repo = RecommendationRepository()

async def insert_recommendation_event(lead_id: str, property_id: str, event: str, match_score: int) -> dict:
    """Helper wrapper function to log state transitions down the conversion pipeline."""
    return await recommendation_repo.insert_recommendation_event(
        lead_id=lead_id,
        property_id=property_id,
        event=event,
        match_score=match_score
    )
