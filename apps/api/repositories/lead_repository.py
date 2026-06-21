# apps/api/repositories/lead_repository.py
from apps.api.schemas.lead_schemas import LeadCreate, LeadUpdate
from datetime import datetime, timezone
from typing import Optional, List


class LeadRepository:
    """Isolates all physical database operations for the Leads collection."""

    @property
    def collection(self):
        """Dynamically fetches the active collection pool via shared database singleton."""
        from shared.utils.database import db
        if db.client is None:
            raise RuntimeError("Database client is not initialized yet.")
        return db.client.nph_core.leads

    async def create_indexes(self):
        """Builds background indexing models for lightning-fast search routing."""
        await self.collection.create_index("id", unique=True, sparse=True)
        await self.collection.create_index("status")
        await self.collection.create_index("created_at")

    async def insert_lead(self, lead_data: LeadCreate) -> dict:
        """Standardizes structural payload shapes and updates the Atlas collection."""
        payload = lead_data.model_dump()
        payload["created_at"] = datetime.now(timezone.utc)
        payload["updated_at"] = datetime.now(timezone.utc)

        await self.collection.insert_one(payload)
        payload.pop("_id", None)
        return payload

    async def get_lead_by_id(self, lead_id: str) -> Optional[dict]:
        return await self.collection.find_one({"id": lead_id}, {"_id": 0})

    async def get_all_leads(self, limit: int = 100, skip: int = 0) -> list:
        cursor = self.collection.find({}, {"_id": 0}).sort("created_at", -1).skip(skip).limit(limit)
        return await cursor.to_list(length=limit)

    async def update_lead(self, lead_id: str, update_data: LeadUpdate) -> Optional[dict]:
        clean_updates = {k: v for k, v in update_data.model_dump(exclude_unset=True).items()}
        if not clean_updates:
            return await self.get_lead_by_id(lead_id)

        clean_updates["updated_at"] = datetime.now(timezone.utc)
        await self.collection.update_one({"id": lead_id}, {"$set": clean_updates})
        return await self.get_lead_by_id(lead_id)

    async def delete_lead(self, lead_id: str) -> bool:
        result = await self.collection.delete_one({"id": lead_id})
        return result.deleted_count > 0