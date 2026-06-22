# apps/api/repositories/webhook_event_repository.py
from apps.api.schemas.webhook_event import WebhookEventCreate
from datetime import datetime, timezone
import uuid


class WebhookEventRepository:
    """Manages raw webhook event persistence and activity logging."""

    @property
    def collection(self):
        """Dynamically fetches the webhook events collection via shared database singleton."""
        from shared.utils.database import db
        if db.client is None:
            raise RuntimeError("Database client is not initialized yet.")
        return db.client.nph_core.webhook_events

    @property
    def activity_collection(self):
        """Dynamically fetches the lead activity collection via shared database singleton."""
        from shared.utils.database import db
        if db.client is None:
            raise RuntimeError("Database client is not initialized yet.")
        return db.client.nph_core.lead_activity

    async def create_indexes(self):
        """Generates indexes for background task processing tracking logs."""
        await self.collection.create_index("event_id", unique=True)
        await self.collection.create_index("processing_status")
        await self.collection.create_index("event_hash", unique=True, sparse=True)
        await self.activity_collection.create_index([("lead_id", 1), ("created_at", -1)])

    async def insert_raw_event(self, event_in: WebhookEventCreate) -> dict:
        """Atomically saves the raw incoming payload to ensure no data is lost."""
        payload = event_in.model_dump()
        payload["event_id"] = f"evt_{uuid.uuid4().hex[:8]}"
        payload["processing_status"] = "pending"
        payload["received_at"] = datetime.now(timezone.utc)

        await self.collection.insert_one(payload)
        payload.pop("_id", None)
        return payload

    async def insert_or_ignore_by_hash(
        self,
        event_hash: str,
        source_group: str,
        raw_text_preview: str
    ) -> dict:
        """
        Idempotent insert for raw chunk ingestion events.

        Attempts to insert a new webhook_event document keyed on 'event_hash'.
        If a document with this hash already exists, returns it with a 'duplicate=True'
        flag so the caller can skip re-queuing the Celery task.

        This guards against double-delivery of the same WhatsApp group copy-paste
        (e.g., a PM refreshing the dashboard or retrying the same paste twice).

        Returns:
            dict with keys: event_id, event_hash, duplicate (bool)
        """
        col = self.collection

        # Check for an existing document with this hash first
        existing = await col.find_one({"event_hash": event_hash})
        if existing:
            existing.pop("_id", None)
            existing["duplicate"] = True
            return existing

        # Build the new idempotent event document
        event_id = f"evt_raw_{uuid.uuid4().hex[:10]}"
        doc = {
            "event_id": event_id,
            "event_hash": event_hash,
            "platform": "whatsapp_group",
            "event_type": "raw_chunk_ingestion",
            "source_group": source_group,
            "raw_text_preview": raw_text_preview,
            "processing_status": "pending",
            "received_at": datetime.now(timezone.utc),
            "duplicate": False,
        }

        try:
            await col.insert_one(doc)
        except Exception:
            # Race condition: another request beat us to the insert.
            # Re-fetch and return the winning document as a duplicate.
            existing = await col.find_one({"event_hash": event_hash})
            if existing:
                existing.pop("_id", None)
                existing["duplicate"] = True
                return existing
            raise

        doc.pop("_id", None)
        return doc

    async def update_status(self, event_id: str, status: str) -> bool:
        result = await self.collection.update_one(
            {"event_id": event_id},
            {"$set": {"processing_status": status, "processed_at": datetime.now(timezone.utc)}}
        )
        return result.modified_count > 0

    async def log_activity(self, lead_id: str, activity_type: str, metadata: dict = None) -> bool:
        """Records granular timeline actions to make scoring lookups simple."""
        activity = {
            "activity_id": f"act_{uuid.uuid4().hex[:8]}",
            "lead_id": lead_id,
            "activity_type": activity_type,
            "metadata": metadata or {},
            "created_at": datetime.now(timezone.utc)
        }
        await self.activity_collection.insert_one(activity)
        return True


webhook_event_repo = WebhookEventRepository()