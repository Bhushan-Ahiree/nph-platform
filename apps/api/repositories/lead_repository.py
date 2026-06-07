# apps/api/repositories/lead_repository.py
from motor.motor_asyncio import AsyncIOMotorClient
from apps.api.schemas.lead_schemas import LeadCreate, LeadUpdate
from datetime import datetime
from typing import Optional, List
import os
import uuid

class LeadRepository:
    def __init__(self):
        self.mongo_url = os.getenv("MONGO_URL") or os.getenv("MONGO_URI")
        self.client = AsyncIOMotorClient(self.mongo_url)
        self.db = self.client["nph_core"]
        self.collection = self.db["leads"]

    async def create_indexes(self):
        """Builds background indexing models for lightning-fast search routing."""
        await self.collection.create_index("phone")
        await self.collection.create_index("lead_id", unique=True)
        await self.collection.create_index("lead_status")
        await self.collection.create_index("hotness_score")
        await self.collection.create_index("created_at")

    async def insert_lead(self, lead_data: LeadCreate) -> dict:
        """Standardizes structural payload shapes and updates the Atlas domain collection."""
        payload = lead_data.dict()
        payload["lead_id"] = f"lead_{uuid.uuid4().hex[:8]}"
        payload["lead_status"] = "new"
        payload["hotness_score"] = 0
        payload["follow_up_count"] = 0
        payload["last_contacted_at"] = None
        payload["site_visit_booked"] = False
        payload["site_visit_paid"] = False
        payload["deal_closed"] = False
        payload["deal_value"] = 0.0
        payload["created_at"] = datetime.utcnow()
        
        await self.collection.insert_one(payload)
        payload.pop("_id", None)
        return payload

    async def get_lead_by_id(self, lead_id: str) -> Optional[dict]:
        return await self.collection.find_one({"lead_id": lead_id}, {"_id": 0})

    async def get_all_leads(self, limit: int = 100, skip: int = 0) -> list:
        cursor = self.collection.find({}, {"_id": 0}).sort("created_at", -1).skip(skip).limit(limit)
        return await cursor.to_list(length=limit)

    async def update_lead(self, lead_id: str, update_data: LeadUpdate) -> Optional[dict]:
        clean_updates = {k: v for k, v in update_data.dict(exclude_unset=True).items()}
        if not clean_updates:
            return await self.get_lead_by_id(lead_id)
            
        await self.collection.update_one({"lead_id": lead_id}, {"$set": clean_updates})
        return await self.get_lead_by_id(lead_id)

    async def delete_lead(self, lead_id: str) -> bool:
        result = await self.collection.delete_one({"lead_id": lead_id})
        return result.deleted_count > 0