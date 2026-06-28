# apps/api/repositories/site_visit_repository.py
from datetime import datetime, timezone
from bson import ObjectId
from typing import List, Optional
from pymongo import ReturnDocument


class SiteVisitRepository:
    """Manages site visit lifecycle persistence for the ground operations pipeline."""

    @property
    def collection(self):
        """Dynamically fetches the site visits collection via shared database singleton."""
        from shared.utils.database import db
        if db.client is None:
            raise RuntimeError("Database client is not initialized yet.")
        return db.client.nph_core.site_visits

    async def create_indexes(self):
        """Indexes to make our analytics dashboards instantly fast."""
        await self.collection.create_index([("status", 1), ("scheduled_at", 1)])
        await self.collection.create_index([("lead_id", 1), ("created_at", -1)])
        await self.collection.create_index("lead_id")
        await self.collection.create_index("status")
        await self.collection.create_index("scheduled_at")

    async def insert_site_visit(self, lead_id: str, property_id: str, scheduled_at: datetime, notes: str = None) -> dict:
        """Writes a new viewing record."""
        payload = {
            "lead_id": lead_id,
            "property_id": property_id,
            "scheduled_at": scheduled_at,
            "status": "SCHEDULED",
            "notes": notes,
            "visit_fee": 100,
            "fee_collected": False,
            "collected_by": None,
            "visit_result": None,
            "deal_closed": False,
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc)
        }
        result = await self.collection.insert_one(payload)
        payload["id"] = str(result.inserted_id)
        if "_id" in payload:
            del payload["_id"]
        return payload

    async def get_site_visits_by_lead(self, lead_id: str) -> List[dict]:
        """Fetches all past and upcoming visits for a specific lead, sorted by created_at descending."""
        cursor = self.collection.find({"lead_id": lead_id}).sort("created_at", -1)
        visits = await cursor.to_list(length=100)
        for v in visits:
            v["id"] = str(v.pop("_id"))
        return visits

    async def get_all_active_site_visits(self) -> List[dict]:
        """Fetches all visits with a status of 'SCHEDULED' for administrator tracking."""
        cursor = self.collection.find({"status": "SCHEDULED"}).sort("scheduled_at", 1)
        visits = await cursor.to_list(length=100)
        for v in visits:
            v["id"] = str(v.pop("_id"))
        return visits

    async def update_site_visit_status(
        self,
        visit_id: str,
        status: Optional[str] = None,
        notes: Optional[str] = None,
        visit_fee: Optional[int] = None,
        fee_collected: Optional[bool] = None,
        collected_by: Optional[str] = None,
        visit_result: Optional[str] = None,
        deal_closed: Optional[bool] = None,
        session = None
    ) -> Optional[dict]:
        """Modifies the status or appends notes/financial details after a visit finishes."""
        update_fields = {}
        if status is not None:
            update_fields["status"] = status
        if notes is not None:
            update_fields["notes"] = notes
        if visit_fee is not None:
            update_fields["visit_fee"] = visit_fee
        if fee_collected is not None:
            update_fields["fee_collected"] = fee_collected
        if collected_by is not None:
            update_fields["collected_by"] = collected_by
        if visit_result is not None:
            update_fields["visit_result"] = visit_result
        if deal_closed is not None:
            update_fields["deal_closed"] = deal_closed

        if not update_fields:
            query = {}
            try:
                query = {"_id": ObjectId(visit_id)}
            except Exception:
                query = {"_id": visit_id}
            doc = await self.collection.find_one(query, session=session)
            if doc:
                doc["id"] = str(doc.pop("_id"))
                return doc
            return None

        update_fields["updated_at"] = datetime.now(timezone.utc)

        query = {}
        try:
            query = {"_id": ObjectId(visit_id)}
        except Exception:
            query = {"_id": visit_id}

        updated_doc = await self.collection.find_one_and_update(
            query,
            {"$set": update_fields},
            return_document=ReturnDocument.AFTER,
            session=session
        )
        if updated_doc:
            updated_doc["id"] = str(updated_doc.pop("_id"))
        return updated_doc


site_visit_repo = SiteVisitRepository()