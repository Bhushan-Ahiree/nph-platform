# apps/api/routes/property.py
from fastapi import APIRouter, HTTPException, status, Depends, Query
from typing import Optional, Any, Dict
import uuid
import hashlib
import json
import os
from datetime import datetime, timezone
from celery import Celery
from pydantic import BaseModel

from apps.api.schemas.property_schema_v2 import PropertyCreate, PropertyDB
from shared.utils.auth_guard import get_current_user
from apps.api.repositories.property_repository import property_repo
from apps.api.schemas.raw_ingestion_schemas import RawChunkIngestionRequest, RawChunkIngestionResponse
from apps.api.repositories.webhook_event_repository import webhook_event_repo


# ---------------------------------------------------------------------------
# Sprint A: Dedicated response schemas for operational verification endpoints
# ---------------------------------------------------------------------------

class VerifyResponse(BaseModel):
    """Response envelope for PATCH /properties/{id}/verify."""
    property_id: str
    status: str
    availability_status: str
    confidence_score: int
    verification_count: int
    last_verified_at: datetime
    message: str


class InactiveResponse(BaseModel):
    """Response envelope for PATCH /properties/{id}/inactive."""
    property_id: str
    status: str
    availability_status: str
    message: str


router = APIRouter(prefix="/properties", tags=["Properties"])


@router.get("/", response_model=list[PropertyDB])
async def get_properties(
    skip: int = 0, limit: int = 50,
    city: Optional[str] = Query(None), locality: Optional[str] = Query(None),
    bhk: Optional[int] = Query(None), property_type: Optional[str] = Query(None),
    min_price: Optional[float] = Query(None), max_price: Optional[float] = Query(None)
):
    # Dynamic query object generation targeting flat V2 schema fields
    mongo_query: Dict[str, Any] = {}
    if city:
        mongo_query["city"] = {"$regex": f"^{city}$", "$options": "i"}
    if locality:
        mongo_query["area"] = {"$regex": locality, "$options": "i"}
    if bhk:
        mongo_query["bhk"] = bhk
    if property_type:
        mongo_query["property_type"] = {"$regex": f"^{property_type}$", "$options": "i"}
    if min_price is not None or max_price is not None:
        mongo_query["price"] = {}
        if min_price is not None:
            mongo_query["price"]["$gte"] = min_price
        if max_price is not None:
            mongo_query["price"]["$lte"] = max_price

    # Clean repository encapsulation execution
    return await property_repo.find_filtered(mongo_query, skip=skip, limit=limit)


@router.post("/", response_model=PropertyDB, status_code=status.HTTP_201_CREATED)
async def create_property(property_in: PropertyCreate, current_user: dict = Depends(get_current_user)):
    property_dict = property_in.model_dump()

    # Clean check via our repository layer abstraction helper using flat V2 fields
    duplicate = await property_repo.check_duplicate(
        property_dict["title"], property_dict["city"], property_dict["area"]
    )
    if duplicate:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A property listing with this title and location already exists."
        )

    property_dict["property_id"] = f"prop_{uuid.uuid4().hex[:8]}"
    property_dict["created_at"] = datetime.now(timezone.utc)
    property_dict["updated_at"] = datetime.now(timezone.utc)
    property_dict["posted_by_user_id"] = current_user["id"]

    return await property_repo.create(property_dict)


@router.patch("/{property_id}", response_model=PropertyDB)
async def update_property(property_id: str, updates: dict, current_user: dict = Depends(get_current_user)):
    banned_updates = ["_id", "id", "property_id", "created_at", "posted_by_user_id"]
    for field in banned_updates:
        updates.pop(field, None)

    if not updates:
        raise HTTPException(status_code=400, detail="No valid fields provided.")

    updates["updated_at"] = datetime.now(timezone.utc)

    result = await property_repo.update(property_id, updates)
    if not result:
        raise HTTPException(status_code=404, detail="Property not found.")
    return result


@router.delete("/{property_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_property(property_id: str, current_user: dict = Depends(get_current_user)):
    success = await property_repo.delete(property_id)
    if not success:
        raise HTTPException(status_code=404, detail="Property not found.")
    return None


@router.patch("/{property_id}/verify", response_model=VerifyResponse)
async def verify_property(property_id: str, current_user: dict = Depends(get_current_user)):
    """
    PATCH /properties/{property_id}/verify

    Single-click manual verification endpoint.

    Transitions the property's 5-state lifecycle back to 'VERIFIED', resets
    the structural confidence_score to 100, increments verification_count by 1,
    and refreshes last_verified_at. This also resets the freshness sweeper
    clock — the property will not be flagged as STALE until the next
    type-appropriate velocity window expires.

    Also increments the broker's 'verified_properties' counter so their
    reliability_score benefits from the verification event.
    """
    col = property_repo.get_collection()
    prop = await col.find_one({"property_id": property_id})
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found.")

    now = datetime.now(timezone.utc)
    new_ver_count = prop.get("verification_count", 0) + 1
    updates = {
        "status": "ACTIVE",
        # Sprint A: canonical 5-state lifecycle value
        "availability_status": "VERIFIED",
        "verification_count": new_ver_count,
        "confidence_score": 100,
        "last_verified_at": now,
        "updated_at": now,
    }
    result = await property_repo.update(property_id, updates)
    if not result:
        raise HTTPException(status_code=404, detail="Property not found.")

    # Broker verified_properties side-effect
    broker_phone = prop.get("broker_phone")
    if not broker_phone:
        broker_phone = prop.get("source", {}).get("broker_phone")
    if broker_phone:
        from apps.api.repositories.broker_repository import broker_repo
        await broker_repo.increment_property_counter(broker_phone, "verified_properties")

    return VerifyResponse(
        property_id=property_id,
        status=result["status"],
        availability_status=result["availability_status"],
        confidence_score=result["confidence_score"],
        verification_count=result["verification_count"],
        last_verified_at=result["last_verified_at"],
        message=f"Property '{property_id}' verified. Clock reset, confidence restored to 100."
    )


@router.patch("/{property_id}/inactive", response_model=InactiveResponse)
@router.patch("/{property_id}/archive", response_model=InactiveResponse)
async def mark_property_inactive(property_id: str, current_user: dict = Depends(get_current_user)):
    """
    PATCH /properties/{property_id}/inactive

    Single-click immediate archival endpoint.

    Immediately updates both availability_status and the core status field to
    'ARCHIVED', dropping the listing instantly from all matching pools and
    search vectors. Use this when a broker confirms a rental is filled or a
    sale is closed, without waiting for the freshness sweeper cycle.

    This is functionally equivalent to the automated ARCHIVED transition
    triggered by the sweeper, but fires synchronously on demand.
    """
    col = property_repo.get_collection()
    prop = await col.find_one({"property_id": property_id})
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found.")

    now = datetime.now(timezone.utc)
    updates = {
        # Sprint A: both the coarse status and the fine-grained lifecycle are set
        "status": "ARCHIVED",
        "availability_status": "ARCHIVED",
        "updated_at": now,
    }
    result = await property_repo.update(property_id, updates)
    if not result:
        raise HTTPException(status_code=404, detail="Property not found.")

    return InactiveResponse(
        property_id=property_id,
        status=result["status"],
        availability_status=result["availability_status"],
        message=f"Property '{property_id}' immediately archived and removed from matching pools."
    )


@router.post(
    "/raw-chunk",
    response_model=RawChunkIngestionResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Ingest a raw WhatsApp broker group chat dump",
    description=(
        "Accepts unformatted copy-pasted text from WhatsApp broker groups. "
        "Creates an idempotent webhook_event entry via payload SHA-256 hash, then "
        "immediately offloads AI extraction to the Celery worker. Returns 202 instantly."
    )
)
async def ingest_raw_group_chunk(payload: RawChunkIngestionRequest):
    """
    POST /properties/raw-chunk

    Pipeline:
    1. Compute a deterministic SHA-256 event_hash over (source_group + raw_text).
    2. Attempt an idempotent insert into webhook_events — if the hash already exists,
       return 202 with a duplicate notice to avoid double-processing.
    3. Dispatch tasks.ingestion_tasks.process_raw_group_dump to Celery asynchronously.
    4. Return 202 Accepted immediately — the caller does NOT wait for AI extraction.
    """
    # ------------------------------------------------------------------ #
    # Step 1 — Compute delivery-guardrail hash over the full payload       #
    # ------------------------------------------------------------------ #
    hash_input = json.dumps(
        {"source_group": payload.source_group, "raw_text": payload.raw_text},
        sort_keys=True
    ).encode("utf-8")
    event_hash = hashlib.sha256(hash_input).hexdigest()

    # ------------------------------------------------------------------ #
    # Step 2 — Idempotent webhook_event upsert                            #
    # ------------------------------------------------------------------ #
    event_doc = await webhook_event_repo.insert_or_ignore_by_hash(
        event_hash=event_hash,
        source_group=payload.source_group,
        raw_text_preview=payload.raw_text[:200]   # store a short preview only
    )

    if event_doc.get("duplicate"):
        # Idempotent delivery: same payload was already queued — return 202 cleanly
        return RawChunkIngestionResponse(
            status="duplicate_skipped",
            event_id=event_doc["event_id"],
            task_id="",
            message="Duplicate payload detected via event hash — already queued."
        )

    # ------------------------------------------------------------------ #
    # Step 3 — Dispatch Celery task for async AI extraction               #
    # ------------------------------------------------------------------ #
    try:
        celery_client = Celery(
            broker=os.getenv("REDIS_URL", "redis://redis:6379/0")
        )
        task = celery_client.send_task(
            "tasks.ingestion_tasks.process_raw_group_dump",
            kwargs={
                "source_group": payload.source_group,
                "raw_text": payload.raw_text,
                "event_id": event_doc["event_id"]
            }
        )
        task_id = task.id
    except Exception as dispatch_err:
        # Log but do not fail the HTTP response — the event is persisted and
        # can be replayed. Task dispatch failures are non-fatal to the client.
        print(f"[RawChunk] Celery dispatch error for event {event_doc['event_id']}: {dispatch_err}")
        task_id = "dispatch_failed"

    # ------------------------------------------------------------------ #
    # Step 4 — Return 202 immediately                                     #
    # ------------------------------------------------------------------ #
    return RawChunkIngestionResponse(
        status="accepted",
        event_id=event_doc["event_id"],
        task_id=task_id,
        message=f"Raw group dump accepted. AI extraction queued for '{payload.source_group}'."
    )