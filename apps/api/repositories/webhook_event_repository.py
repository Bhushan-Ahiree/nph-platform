# apps/api/repositories/webhook_event_repository.py
from motor.motor_asyncio import AsyncIOMotorClient
from apps.api.schemas.webhook_event import WebhookEventCreate
from datetime import datetime
import os
import uuid

class WebhookEventRepository:
    def __init__(self):
        self.mongo_url = os.getenv("MONGO_URL") or os.getenv("MONGO_URI")
        self.client = AsyncIOMotorClient(self.mongo_url)
        self.db = self.client["nph_core"]
        self.collection = self.db["webhook_events"]
        self.activity_collection = self.db["lead_activity"]

    async def create_indexes(self):
        """Generates indexes for background task processing tracking logs."""
        await self.collection.create_index("event_id", unique=True)
        await self.collection.create_index("processing_status")
        await self.activity_collection.create_index([("lead_id", 1), ("created_at", -1)])

    async def insert_raw_event(self, event_in: WebhookEventCreate) -> dict:
        """Atomically saves the raw incoming payload to ensure no data is lost."""
        payload = event_in.dict()
        payload["event_id"] = f"evt_{uuid.uuid4().hex[:8]}"
        payload["processing_status"] = "pending"
        payload["received_at"] = datetime.utcnow()
        
        await self.collection.insert_one(payload)
        payload.pop("_id", None)
        return payload

    async def update_status(self, event_id: str, status: str) -> bool:
        result = await self.collection.update_one(
            {"event_id": event_id},
            {"$set": {"processing_status": status, "processed_at": datetime.utcnow()}}
        )
        return result.modified_count > 0

    async def log_activity(self, lead_id: str, activity_type: str, metadata: dict = None) -> bool:
        """Records granular timeline actions to make scoring lookups simple."""
        activity = {
            "activity_id": f"act_{uuid.uuid4().hex[:8]}",
            "lead_id": lead_id,
            "activity_type": activity_type,
            "metadata": metadata or {},
            "created_at": datetime.utcnow()
        }
        await self.activity_collection.insert_one(activity)
        return True