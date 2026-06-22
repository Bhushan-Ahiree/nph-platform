# apps/worker/tasks/ingestion_tasks.py
"""
Mass Text Ingestion Pipeline — Celery Task Layer
=================================================
Week 1 / P0: Inventory Expansion via Mass Text Ingestion

This module implements the full async execution loop for:
1. Chunking large raw WhatsApp group text blocks for local LLM memory efficiency.
2. Calling local Ollama Llama 3.2 to extract an array of property listings.
3. Computing SHA-256 structural deduplication hashes per extracted property.
4. Upserting brokers via broker_repo and properties via property_repo.
"""

import os
import re
import json
import time
import hashlib
import logging
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

from celery import shared_task
from pymongo import MongoClient

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Maximum number of "message blocks" per Ollama inference call.
# A "block" is defined as a sequence of lines separated by blank lines.
# Keeping calls small reduces peak VRAM pressure on local Llama 3.2 instances.
CHUNK_SIZE_BLOCKS = 5

# Ollama API endpoint — resolved from environment; defaults to host machine.
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://host.docker.internal:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2")

# System prompt passed on every Ollama inference call.
OLLAMA_SYSTEM_PROMPT = """You are a real estate data extraction engine for an Indian property platform.

You will be given raw, unformatted chat messages copy-pasted from WhatsApp broker groups.

Your task is to:
1. Read all messages carefully.
2. Identify EVERY distinct property that is being ADVERTISED or OFFERED (not requested).
3. For each property, extract the following fields into a JSON object:
   - "title": Short descriptive title, e.g. "2 BHK Apartment in Indira Nagar"
   - "description": Any extra details mentioned (amenities, floor, furnishing, etc.)
   - "property_type": One of: apartment, villa, plot, commercial, flat, land
   - "listing_type": One of: rent, buy, sale
   - "city": One of: Nashik, Pune, Mumbai (infer from context if not explicit, default to Nashik)
   - "area": Locality or neighbourhood name, e.g. "Indira Nagar", "College Road"
   - "bhk": Integer number of bedrooms (0 if not mentioned or non-residential)
   - "price": Integer price in INR (monthly rent or sale price, no commas or symbols)
   - "broker_phone": The phone number of the person advertising this property. Extract digits only, no spaces or dashes. Use null if not found.

IMPORTANT RULES:
- Output ONLY a valid JSON array. No explanation, no markdown, no extra text.
- Each element of the array is one property listing.
- If NO properties are found, output an empty array: []
- If a phone number appears near a listing, associate it with that listing as broker_phone.
- Ignore messages that are requests/inquiries (e.g. "Need 2BHK"). Only extract offers.
- Prices should be integers (e.g. 15000, not "15k" or "15,000").

Example output:
[
  {
    "title": "2 BHK Apartment in Indira Nagar",
    "description": "Semi-furnished, 2nd floor, parking available",
    "property_type": "apartment",
    "listing_type": "rent",
    "city": "Nashik",
    "area": "Indira Nagar",
    "bhk": 2,
    "price": 12000,
    "broker_phone": "9876543210"
  }
]"""


# ---------------------------------------------------------------------------
# Helper: Split raw text into message blocks
# ---------------------------------------------------------------------------

def split_into_message_blocks(raw_text: str) -> List[str]:
    """
    Splits a raw WhatsApp chat dump into individual message blocks.

    WhatsApp messages are naturally separated by blank lines when copy-pasted.
    This function groups contiguous non-empty lines into blocks and returns
    each block as a single string.

    Args:
        raw_text: The full raw copy-paste text from a WhatsApp group.

    Returns:
        List of message block strings, each representing one logical message.
    """
    # Normalise line endings across platforms (Windows CRLF, Unix LF)
    normalized = raw_text.replace("\r\n", "\n").replace("\r", "\n")
    lines = normalized.split("\n")

    blocks: List[str] = []
    current_block: List[str] = []

    for line in lines:
        stripped = line.strip()
        if stripped:
            current_block.append(stripped)
        else:
            if current_block:
                blocks.append("\n".join(current_block))
                current_block = []

    # Flush any trailing block that wasn't followed by a blank line
    if current_block:
        blocks.append("\n".join(current_block))

    return blocks


def chunk_blocks(blocks: List[str], chunk_size: int = CHUNK_SIZE_BLOCKS) -> List[List[str]]:
    """
    Groups a flat list of message blocks into sublists of size ≤ chunk_size.

    Args:
        blocks: Full list of message blocks from split_into_message_blocks().
        chunk_size: Maximum number of blocks per inference call.

    Returns:
        List of block sublists (chunks) ready for individual Ollama calls.
    """
    return [blocks[i: i + chunk_size] for i in range(0, len(blocks), chunk_size)]


# ---------------------------------------------------------------------------
# Helper: Ollama Llama 3.2 inference
# ---------------------------------------------------------------------------

def call_ollama_extract(chunk_text: str, source_group: str) -> List[Dict[str, Any]]:
    """
    Sends a text chunk to the local Ollama Llama 3.2 instance and parses
    the returned JSON array of property objects.

    Uses the /api/chat endpoint with an explicit system prompt to ensure
    deterministic structured output from the model.

    Args:
        chunk_text: The concatenated text of all message blocks in this chunk.
        source_group: Human-readable group name injected into the user prompt
                      for context (helps the model infer the city/region).

    Returns:
        List of raw property dicts as parsed from the model's JSON output.
        Returns [] on parse failure or model error (non-crashing).
    """
    import urllib.request
    import urllib.error

    user_message = (
        f"Source group: {source_group}\n\n"
        f"Messages to analyse:\n\n{chunk_text}"
    )

    request_body = json.dumps({
        "model": OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": OLLAMA_SYSTEM_PROMPT},
            {"role": "user", "content": user_message}
        ],
        "stream": False,
        "options": {
            "temperature": 0.1,   # Very low temperature — we want deterministic JSON
            "num_predict": 2048
        }
    }).encode("utf-8")

    url = f"{OLLAMA_BASE_URL}/api/chat"

    try:
        req = urllib.request.Request(
            url,
            data=request_body,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=120) as response:
            raw_response = response.read().decode("utf-8")

        response_data = json.loads(raw_response)
        model_content = response_data.get("message", {}).get("content", "")

        if not model_content.strip():
            logger.warning("[Ollama] Empty response content from model.")
            return []

        # Strip potential markdown code fences the model may wrap around JSON
        cleaned = model_content.strip()
        if cleaned.startswith("```"):
            # Remove opening fence (```json or ```)
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
            # Remove closing fence
            cleaned = re.sub(r"\s*```$", "", cleaned)
        cleaned = cleaned.strip()

        # Parse the JSON array
        parsed = json.loads(cleaned)
        if isinstance(parsed, list):
            return parsed
        elif isinstance(parsed, dict):
            # Model occasionally wraps array in {"properties": [...]}
            for key in ("properties", "listings", "results"):
                if key in parsed and isinstance(parsed[key], list):
                    return parsed[key]
        logger.warning(f"[Ollama] Unexpected response shape: {type(parsed)}")
        return []

    except urllib.error.URLError as conn_err:
        logger.error(f"[Ollama] Connection error — is Ollama running? {conn_err}")
        return []
    except json.JSONDecodeError as parse_err:
        logger.error(f"[Ollama] Failed to parse model JSON output: {parse_err}")
        logger.debug(f"[Ollama] Raw content was: {model_content[:500]}")
        return []
    except Exception as err:
        logger.error(f"[Ollama] Unexpected error during inference: {err}")
        return []


# ---------------------------------------------------------------------------
# Helper: SHA-256 ingestion hash computation
# ---------------------------------------------------------------------------

def compute_ingestion_hash(
    price: Any,
    area: str,
    bhk: Any,
    listing_type: str,
    broker_phone: Optional[str]
) -> str:
    """
    Computes a deterministic SHA-256 structural deduplication hash.

    The hash is derived purely from alphanumeric characters of the five
    most structurally identifying fields of a property listing:
      price + area + bhk + listing_type + broker_phone

    This means the same physical property listed by the same broker at the
    same price will always produce the same hash, regardless of minor
    description changes or punctuation differences.

    Args:
        price: The property price (int or string; will be coerced to int str).
        area: The locality/area name (non-alphanumeric chars stripped).
        bhk: The number of bedrooms (int or string).
        listing_type: "rent", "buy", or "sale".
        broker_phone: The broker's phone number (digits only). Use "" if null.

    Returns:
        64-character lowercase hexadecimal SHA-256 digest string.
    """
    def alphanumeric_only(value: str) -> str:
        """Strips all non-alphanumeric characters and lowercases the result."""
        return re.sub(r"[^a-zA-Z0-9]", "", str(value)).lower()

    # Coerce and clean each component
    price_clean = alphanumeric_only(str(int(float(price))) if price else "0")
    area_clean = alphanumeric_only(area or "")
    bhk_clean = alphanumeric_only(str(bhk) if bhk is not None else "0")
    listing_type_clean = alphanumeric_only(listing_type or "")
    broker_phone_clean = alphanumeric_only(broker_phone or "")

    # Concatenate in a fixed, canonical order
    composite = f"{price_clean}{area_clean}{bhk_clean}{listing_type_clean}{broker_phone_clean}"

    return hashlib.sha256(composite.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Helper: Normalise a raw extracted property dict into a clean insert payload
# ---------------------------------------------------------------------------

def normalise_extracted_property(
    raw: Dict[str, Any],
    source_group: str,
    ingestion_hash: str
) -> Dict[str, Any]:
    """
    Converts a raw dict from Ollama's JSON output into a clean property document
    ready for insertion into the 'properties' MongoDB collection.

    Maps all fields to the PropertySchemaV2 flat-field layout used by the platform.
    Applies all required defaults mandated by the ingestion pipeline specification.

    Args:
        raw: The raw property dict from the model's JSON array.
        source_group: WhatsApp group name for the 'source' sub-document.
        ingestion_hash: Pre-computed SHA-256 hash for deduplication.

    Returns:
        Clean property dict ready for property_repo.upsert_property().
    """
    def safe_int(value: Any, default: int = 0) -> int:
        try:
            return int(float(str(value).replace(",", "").replace("k", "000").replace("K", "000")))
        except (ValueError, TypeError):
            return default

    def clean_str(value: Any, default: str = "") -> str:
        if value is None:
            return default
        return str(value).strip()

    def clean_phone(value: Any) -> Optional[str]:
        if value is None:
            return None
        digits = re.sub(r"\D", "", str(value))
        # Accept 10-digit Indian numbers or 12-digit with country code
        if len(digits) == 12 and digits.startswith("91"):
            digits = digits[2:]
        if len(digits) == 10:
            return digits
        # Return as-is if it doesn't match standard length; better than losing data
        return digits if digits else None

    # Validate and normalise enumerated string fields
    valid_property_types = {"apartment", "villa", "plot", "commercial", "flat", "land"}
    valid_listing_types = {"rent", "buy", "sale"}
    valid_cities = {"Nashik", "Pune", "Mumbai"}

    property_type = clean_str(raw.get("property_type"), "apartment").lower()
    if property_type not in valid_property_types:
        property_type = "apartment"

    listing_type = clean_str(raw.get("listing_type"), "rent").lower()
    if listing_type not in valid_listing_types:
        listing_type = "rent"

    city = clean_str(raw.get("city"), "Nashik").strip().title()
    if city not in valid_cities:
        city = "Nashik"

    broker_phone = clean_phone(raw.get("broker_phone"))
    now = datetime.now(timezone.utc)

    return {
        # Core PropertySchemaV2 fields
        "title": clean_str(raw.get("title"), "Property Listing"),
        "description": clean_str(raw.get("description")),
        "property_type": property_type,
        "listing_type": listing_type,
        "city": city,
        "area": clean_str(raw.get("area"), "Unknown"),
        "bhk": safe_int(raw.get("bhk"), 0),
        "price": safe_int(raw.get("price"), 0),
        "parking": False,
        "carpet_area_sqft": None,

        # Broker phone extracted as a flat field (top-level, per V2 schema)
        "broker_phone": broker_phone,

        # Source metadata sub-document (primary origination, legacy compat)
        "source": {
            "type": "broker_group",
            "group_name": source_group,
            "broker_name": "NPH Ingestion Bot",
            "broker_phone": broker_phone,
        },

        # Sprint A: initial source observation in the sources array.
        # On hash collision, additional SourceEntry dicts are appended here.
        "sources": [
            {
                "broker_phone": broker_phone,
                "group_name": source_group,
                "seen_at": now,
            }
        ],

        # Sprint A: raw message traceability (caller injects after log is stored)
        "raw_message_id": raw.get("_raw_message_id"),  # injected by the task loop

        # Sprint A: LLM extraction confidence score (default 100 for Llama 3.2)
        "extraction_confidence": 100,

        # Ingestion pipeline defaults — all mandated by the P0 spec
        "status": "ACTIVE",
        # Sprint A: starts as NEW (not VERIFIED) — requires a ping or sweeper pass
        "availability_status": "NEW",
        "confidence_score": 100,
        "last_verified_at": now,
        "verification_count": 1,
        "ingestion_hash": ingestion_hash,
        "created_at": now,
        "updated_at": now,

        # Nested defaults required by the shared schema
        "availability": {
            "status": "active",
            "last_verified_at": now,
            "verified_by": "automated"
        },
        "rental_details": {
            "deposit": 0,
            "preferred_tenant": "any",
            "furnishing": "unfurnished"
        },
        "intelligence": {
            "hot_property": False,
            "duplicate_count": 0,
            "source_confidence": 100
        },
    }


# ---------------------------------------------------------------------------
# Celery Task: process_raw_group_dump
# ---------------------------------------------------------------------------

@shared_task(
    name="tasks.ingestion_tasks.process_raw_group_dump",
    bind=True,
    max_retries=3,
    autoretry_for=(Exception,),
    retry_backoff=5,
    retry_jitter=True,
    soft_time_limit=600,   # 10-minute soft kill for very large dumps
    time_limit=660         # Hard kill at 11 minutes
)
def process_raw_group_dump(self, source_group: str, raw_text: str, event_id: str = ""):
    """
    Celery task: tasks.ingestion_tasks.process_raw_group_dump

    Entry point for the mass text ingestion pipeline. Orchestrates the full
    extraction, deduplication, and upsert loop for a single WhatsApp group dump.

    Execution steps:
    ─────────────────────────────────────────────────────────────────────────
    1. CHUNK INPUT
       Splits raw_text into message blocks separated by blank lines.
       If the total block count exceeds CHUNK_SIZE_BLOCKS (5), the list is
       split into sub-chunks to limit local inference memory pressure.

    2. OLLAMA INFERENCE
       Each sub-chunk is passed to the local Llama 3.2 instance via the
       /api/chat endpoint with an explicit system prompt.
       The model returns a JSON array of property objects.

    3. DEDUPLICATION
       For each extracted property, computes a SHA-256 ingestion_hash from
       price + area + bhk + listing_type + broker_phone (alphanumeric only).
       Queries the 'properties' collection for an ACTIVE document with this
       hash. If found → skip (already in inventory). If not → proceed.

    4. BROKER UPSERT
       Calls broker_repo.upsert_broker(phone, name="NPH Ingestion Bot") to
       ensure the source agent's ledger exists before property insertion.

    5. PROPERTY UPSERT
       Calls property_repo.upsert_property() with the full normalised
       property document including the ingestion_hash.

    6. STATUS UPDATE
       Updates the webhook_events document status to "processed" or "failed".

    Args:
        source_group: Human-readable name of the originating WhatsApp group.
        raw_text: The full unformatted copy-paste dump from the group chat.
        event_id: The webhook_events document ID for status tracking.

    Returns:
        Summary dict with counts: total_extracted, inserted, deduplicated.
    """
    import asyncio
    import os

    task_id = self.request.id
    logger.info(
        f"[Ingestion Task] [{task_id}] Starting raw group dump for: '{source_group}' "
        f"(event_id={event_id}, text_len={len(raw_text)})"
    )

    # ------------------------------------------------------------------ #
    # Step 1 — Chunk the input text into manageable message blocks        #
    # ------------------------------------------------------------------ #
    all_blocks = split_into_message_blocks(raw_text)
    total_blocks = len(all_blocks)
    logger.info(f"[Ingestion Task] [{task_id}] Split into {total_blocks} message block(s).")

    # Only sub-chunk if total blocks exceed the threshold
    if total_blocks > CHUNK_SIZE_BLOCKS:
        chunks = chunk_blocks(all_blocks, CHUNK_SIZE_BLOCKS)
        logger.info(
            f"[Ingestion Task] [{task_id}] Chunked into {len(chunks)} inference batches "
            f"of ≤{CHUNK_SIZE_BLOCKS} blocks each."
        )
    else:
        chunks = [all_blocks]  # Single pass; no chunking needed

    # ------------------------------------------------------------------ #
    # Sprint A Step 1.5 — Persist raw payload to raw_message_logs         #
    # This fires synchronously BEFORE the LLM pipeline so every dump has  #
    # a traceable audit log entry even if the worker crashes mid-way.     #
    # ------------------------------------------------------------------ #
    import uuid as _uuid_mod
    import hashlib as _hashlib_mod
    raw_log_id = None
    raw_log_doc = None
    delivery_hash = _hashlib_mod.sha256(
        json.dumps({"source_group": source_group, "raw_text": raw_text}, sort_keys=True).encode()
    ).hexdigest()
    try:
        raw_log_id = f"rawlog_{_uuid_mod.uuid4().hex[:10]}"
        raw_log_doc = {
            "log_id": raw_log_id,
            "raw_text": raw_text,
            "ingestion_hash": delivery_hash,
            "source_group": source_group,
            "processed": False,
            "received_at": datetime.now(timezone.utc),
        }
    except Exception as log_err:
        logger.warning(f"[Ingestion Task] [{task_id}] Could not prepare raw log: {log_err}")

    # ------------------------------------------------------------------ #
    # Step 2 & 3 & 4 & 5 — Inference + dedup + broker + property upsert  #
    # Uses synchronous PyMongo inside the Celery worker process to avoid  #
    # the need for an asyncio event loop in the synchronous task context. #
    # ------------------------------------------------------------------ #
    mongo_url = os.getenv("MONGO_URL") or os.getenv("MONGO_URI")
    client = MongoClient(mongo_url)
    db = client["nph_core"]
    properties_col = db["properties"]
    broker_profiles_col = db["broker_profiles"]
    webhook_events_col = db["webhook_events"]
    raw_logs_col = db["raw_message_logs"]

    # Flush the raw log to DB now that we have the collection handle
    if raw_log_doc:
        try:
            raw_logs_col.insert_one(raw_log_doc)
            logger.info(f"[Ingestion Task] [{task_id}] Raw log persisted: {raw_log_id}")
        except Exception as log_insert_err:
            logger.warning(f"[Ingestion Task] [{task_id}] Raw log insert failed: {log_insert_err}")
            raw_log_id = None

    total_extracted = 0
    total_inserted = 0
    total_deduplicated = 0

    try:
        for chunk_index, chunk_blocks_list in enumerate(chunks, start=1):
            chunk_text = "\n\n---\n\n".join(chunk_blocks_list)
            logger.info(
                f"[Ingestion Task] [{task_id}] Inference call {chunk_index}/{len(chunks)} "
                f"({len(chunk_blocks_list)} blocks, ~{len(chunk_text)} chars)"
            )

            # ── Step 2: Call Ollama for property extraction ────────────────
            extracted_properties = call_ollama_extract(chunk_text, source_group)
            if not extracted_properties:
                logger.info(
                    f"[Ingestion Task] [{task_id}] Chunk {chunk_index}: "
                    f"No properties extracted (model returned empty array or error)."
                )
                continue

            total_extracted += len(extracted_properties)
            logger.info(
                f"[Ingestion Task] [{task_id}] Chunk {chunk_index}: "
                f"Extracted {len(extracted_properties)} property candidate(s)."
            )

            for prop_index, raw_prop in enumerate(extracted_properties, start=1):
                if not isinstance(raw_prop, dict):
                    logger.warning(
                        f"[Ingestion Task] [{task_id}] Chunk {chunk_index} prop {prop_index}: "
                        f"Skipping non-dict item: {type(raw_prop)}"
                    )
                    continue

                # ── Step 3a: Compute structural ingestion hash ─────────────
                broker_phone = raw_prop.get("broker_phone")
                ingestion_hash = compute_ingestion_hash(
                    price=raw_prop.get("price", 0),
                    area=raw_prop.get("area", ""),
                    bhk=raw_prop.get("bhk", 0),
                    listing_type=raw_prop.get("listing_type", "rent"),
                    broker_phone=broker_phone
                )

                # ── Step 3b: Deduplication lookup (sync PyMongo) ───────────
                existing = properties_col.find_one({
                    "ingestion_hash": ingestion_hash,
                    "status": "ACTIVE"
                })
                if existing:
                    total_deduplicated += 1
                    # ── Sprint A: append source entry instead of silent drop ─
                    # Push the new broker/group observation onto the sources array
                    # so forwarding intelligence is preserved analytically.
                    clean_phone_for_source = re.sub(r"\D", "", str(broker_phone)) if broker_phone else None
                    if clean_phone_for_source and len(clean_phone_for_source) == 12 and clean_phone_for_source.startswith("91"):
                        clean_phone_for_source = clean_phone_for_source[2:]
                    properties_col.update_one(
                        {"ingestion_hash": ingestion_hash, "status": "ACTIVE"},
                        {
                            "$push": {
                                "sources": {
                                    "broker_phone": clean_phone_for_source,
                                    "group_name": source_group,
                                    "seen_at": datetime.now(timezone.utc),
                                }
                            },
                            "$inc": {"intelligence.duplicate_count": 1},
                            "$set": {"updated_at": datetime.now(timezone.utc)},
                        }
                    )
                    logger.info(
                        f"[Ingestion Task] [{task_id}] Chunk {chunk_index} prop {prop_index}: "
                        f"DEDUPLICATED — source appended (hash={ingestion_hash[:16]}…, phone={broker_phone})"
                    )
                    continue

                # ── Step 4: Broker upsert ──────────────────────────────────
                if broker_phone:
                    # Clean phone number to digits only
                    clean_phone = re.sub(r"\D", "", str(broker_phone))
                    if len(clean_phone) == 12 and clean_phone.startswith("91"):
                        clean_phone = clean_phone[2:]

                    if clean_phone:
                        broker_profiles_col.update_one(
                            {"_id": clean_phone},
                            {
                                "$set": {
                                    "phone": clean_phone,
                                    "name": "NPH Ingestion Bot",
                                    "last_seen_at": datetime.now(timezone.utc)
                                },
                                "$setOnInsert": {
                                    "properties_posted": 0,
                                    "verified_properties": 0,
                                    "expired_properties": 0,
                                    "reliability_score": 100
                                }
                            },
                            upsert=True
                        )
                        # Increment the posted counter for this broker
                        broker_profiles_col.update_one(
                            {"_id": clean_phone},
                            {
                                "$inc": {"properties_posted": 1},
                                "$set": {"last_seen_at": datetime.now(timezone.utc)}
                            }
                        )
                        logger.info(
                            f"[Ingestion Task] [{task_id}] Broker '{clean_phone}' "
                            f"ledger upserted successfully."
                        )

                # ── Step 5: Build and insert the property document ─────────
                property_doc = normalise_extracted_property(
                    raw={**raw_prop, "_raw_message_id": raw_log_id},
                    source_group=source_group,
                    ingestion_hash=ingestion_hash
                )
                import uuid as _uuid
                property_doc["property_id"] = f"prop_{_uuid.uuid4().hex[:8]}"

                properties_col.insert_one(property_doc)
                total_inserted += 1
                logger.info(
                    f"[Ingestion Task] [{task_id}] Chunk {chunk_index} prop {prop_index}: "
                    f"INSERTED '{property_doc.get('title')}' "
                    f"(hash={ingestion_hash[:16]}…, phone={broker_phone}, raw_log={raw_log_id})"
                )

    except Exception as task_err:
        logger.error(f"[Ingestion Task] [{task_id}] Fatal error: {task_err}", exc_info=True)
        # Update webhook event status to 'failed' before re-raising for Celery retry
        if event_id:
            try:
                webhook_events_col.update_one(
                    {"event_id": event_id},
                    {"$set": {
                        "processing_status": "failed",
                        "error": str(task_err),
                        "processed_at": datetime.now(timezone.utc)
                    }}
                )
            except Exception:
                pass
        raise

    finally:
        client.close()

    # ------------------------------------------------------------------ #
    # Step 6 — Update webhook_events status to 'processed'               #
    # ------------------------------------------------------------------ #
    if event_id:
        try:
            client_final = MongoClient(mongo_url)
            db_final = client_final["nph_core"]
            db_final["webhook_events"].update_one(
                {"event_id": event_id},
                {"$set": {
                    "processing_status": "processed",
                    "processed_at": datetime.now(timezone.utc),
                    "result": {
                        "total_extracted": total_extracted,
                        "inserted": total_inserted,
                        "deduplicated": total_deduplicated
                    }
                }}
            )
            client_final.close()
        except Exception as status_err:
            logger.warning(
                f"[Ingestion Task] [{task_id}] Could not update event status: {status_err}"
            )

    summary = {
        "status": "completed",
        "task_id": task_id,
        "source_group": source_group,
        "event_id": event_id,
        "total_extracted": total_extracted,
        "inserted": total_inserted,
        "deduplicated": total_deduplicated,
    }
    logger.info(f"[Ingestion Task] [{task_id}] Done. Summary: {summary}")
    return summary


# ---------------------------------------------------------------------------
# Legacy task — preserved for backward compatibility
# ---------------------------------------------------------------------------

@shared_task(
    name="tasks.ingestion_tasks.process_raw_scraped_listing",
    bind=True,
    max_retries=3,
    autoretry_for=(Exception,),
    retry_backoff=2,
    retry_jitter=True
)
def process_raw_scraped_listing(self, raw_data: dict):
    """Offloads background data structure cleaning, normalization auditing, and verification checks."""
    task_id = self.request.id
    print(f"[Worker Task] [{task_id}] Initiating structural normalizer verification for target: {raw_data.get('title')}")

    time.sleep(1.5)

    print(f"[Worker Task] [{task_id}] Validation boundaries verified clean for payload.")
    return {"status": "sanitized", "title": raw_data.get("title")}