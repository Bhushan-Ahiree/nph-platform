# apps/api/repositories/raw_message_repository.py
"""
Sprint A — Raw Message Storage Repository
==========================================
Manages the 'raw_message_logs' collection.

Every WhatsApp broker group dump is persisted here BEFORE the LLM extraction
pipeline fires. This provides:
  - A full audit trail of every raw text payload ever ingested.
  - A replay mechanism if the LLM fails or produces bad output.
  - A linkage point: each extracted property stores its 'raw_message_id' so
    engineers can trace the exact source text that produced a given listing.
  - An analytics surface for future quality / confidence analysis.
"""
import uuid
from datetime import datetime, timezone
from typing import Optional


class RawMessageRepository:
    """Handles all persistence operations for the 'raw_message_logs' collection."""

    @property
    def collection(self):
        """Dynamically fetches the raw_message_logs collection via the shared DB singleton."""
        from shared.utils.database import db
        if db.client is None:
            raise RuntimeError("Database client is not initialized yet.")
        return db.client.nph_core.raw_message_logs

    async def create_indexes(self):
        """
        Builds background indexes required for efficient log querying.

        Indexes:
          - ingestion_hash: For fast dedup lookups linking back from property docs.
          - processed: For sweeper tasks that scan un-processed log entries.
          - received_at: For time-range analytics queries.
        """
        await self.collection.create_index("ingestion_hash")
        await self.collection.create_index("processed")
        await self.collection.create_index([("received_at", -1)])

    async def insert_raw_log(
        self,
        raw_text: str,
        ingestion_hash: str,
        source_group: Optional[str] = None,
    ) -> str:
        """
        Persists a raw group dump payload BEFORE the LLM extraction pipeline fires.

        This is the first write in the ingestion pipeline. The returned log ID is
        passed downstream so each extracted property document can store its
        'raw_message_id' — creating a traceable chain from raw text to clean listing.

        Args:
            raw_text: The full unformatted copy-paste text from a WhatsApp group.
            ingestion_hash: SHA-256 hash of the delivery payload (matches webhook_events).
            source_group: Human-readable WhatsApp group name (optional, for filtering).

        Returns:
            str: The generated 'log_id' identifier (e.g. 'rawlog_abc12345de').
        """
        log_id = f"rawlog_{uuid.uuid4().hex[:10]}"
        doc = {
            "log_id": log_id,
            "raw_text": raw_text,
            "ingestion_hash": ingestion_hash,
            "source_group": source_group,
            "processed": False,
            "received_at": datetime.now(timezone.utc),
        }
        await self.collection.insert_one(doc)
        return log_id

    async def mark_processed(self, log_id: str) -> bool:
        """
        Marks a raw log entry as processed after the LLM pipeline completes.

        Args:
            log_id: The identifier returned by insert_raw_log().

        Returns:
            bool: True if the document was found and updated, False otherwise.
        """
        result = await self.collection.update_one(
            {"log_id": log_id},
            {
                "$set": {
                    "processed": True,
                    "processed_at": datetime.now(timezone.utc),
                }
            },
        )
        return result.modified_count > 0

    async def get_by_log_id(self, log_id: str) -> Optional[dict]:
        """
        Retrieves a raw log entry by its identifier.

        Used during debugging and quality review to inspect the exact source text
        that produced a given property listing.
        """
        doc = await self.collection.find_one({"log_id": log_id})
        if doc:
            doc.pop("_id", None)
        return doc

    async def get_unprocessed(self, limit: int = 100) -> list:
        """
        Returns raw log entries that have not yet been fully processed.

        Useful for a replay/recovery task if the worker crashed mid-pipeline.
        """
        cursor = self.collection.find({"processed": False}).sort("received_at", 1).limit(limit)
        docs = await cursor.to_list(length=limit)
        for doc in docs:
            doc.pop("_id", None)
        return docs


raw_message_repo = RawMessageRepository()
