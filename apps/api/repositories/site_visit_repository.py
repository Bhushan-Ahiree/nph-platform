import os
from datetime import datetime, timezone
from motor.motor_asyncio import AsyncIOMotorClient
from bson import ObjectId
from typing import List, Optional
from apps.api.schemas.site_visit_schemas import SiteVisitCreate, SiteVisitUpdate

class SiteVisitRepository:
    def __init__(self):
        self.mongo_url = os.getenv("MONGO_URL") or os.getenv("MONGO_URI")
        self.client = AsyncIOMotorClient(self.mongo_url)
        self.db = self.client["nph_core"]
        self.collection = self.db["site_visits"]

    async def create_indexes(self):
        """Indexes to make our analytics dashboards instantly fast."""
        await self.collection.create_index("lead_id")
        await self.collection.create_index("property_id")
        await self.collection.create_index("status")
        await self.collection.create_index("broker_name")

    async def create_visit(self, visit: SiteVisitCreate) -> dict:
        """Inserts a new requested site visit into the pipeline."""
        visit_dict = visit.dict()
        visit_dict["status"] = "requested"
        visit_dict["outcome"] = "pending"
        visit_dict["created_at"] = datetime.now(timezone.utc)
        visit_dict["updated_at"] = datetime.now(timezone.utc)

        result = await self.collection.insert_one(visit_dict)
        visit_dict["_id"] = str(result.inserted_id)
        return visit_dict

    async def update_visit(self, visit_id: str, update_data: SiteVisitUpdate) -> Optional[dict]:
        """Mom's operation function: Updates status, collects fees, and logs feedback."""
        update_dict = {k: v for k, v in update_data.dict().items() if v is not None}
        if not update_dict:
            return None

        update_dict["updated_at"] = datetime.now(timezone.utc)

        updated_doc = await self.collection.find_one_and_update(
            {"_id": ObjectId(visit_id)},
            {"$set": update_dict},
            return_document=True
        )
        
        if updated_doc:
            updated_doc["_id"] = str(updated_doc["_id"])
        return updated_doc

    async def get_visits_for_lead(self, lead_id: str) -> List[dict]:
        """Fetches all past and upcoming visits for a specific lead."""
        cursor = self.collection.find({"lead_id": lead_id}).sort("created_at", -1)
        visits = await cursor.to_list(length=50)
        for v in visits:
            v["_id"] = str(v["_id"])
        return visits

site_visit_repo = SiteVisitRepository()