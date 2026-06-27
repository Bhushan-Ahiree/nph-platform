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
   - "ownership_type": One of: "owner", "broker"
     Set to "owner" if the message says: "direct owner", "owner", "malik", "no brokerage", "malak", "brokerage free", "direct deal".
     Set to "broker" if the message says: "broker", "agent", or has no clear ownership indicator.
     Default to "broker" if unsure.

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
    "broker_phone": "9876543210",
    "ownership_type": "broker"
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
# Helpers: SHA-256 ingestion hash and normalization imported from shared
# ---------------------------------------------------------------------------
from shared.utils.normalization import compute_ingestion_hash, normalise_extracted_property


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
                                    "reliability_score": 100,
                                    "verified": False
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
                
                # Trigger reverse matching for the newly inserted property
                notify_matching_leads.delay({
                    "property_id": property_doc["property_id"],
                    "area": property_doc["area"],
                    "bhk": property_doc["bhk"],
                    "listing_type": property_doc["listing_type"],
                    "price": property_doc["price"],
                    "broker_phone": property_doc.get("broker_phone"),
                    "ownership_type": property_doc.get("ownership_type", "broker"),
                })

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
# Reverse Matching Task — notifies leads when a matching property is ingested
# ---------------------------------------------------------------------------

@shared_task(
    name="tasks.ingestion_tasks.notify_matching_leads",
    bind=True,
    max_retries=3,
    autoretry_for=(Exception,),
    retry_backoff=2,
    retry_jitter=True
)
def notify_matching_leads(self, property_doc: dict):
    """
    Reverse matching: when a new property is inserted,
    find all MATCHABLE or PROPERTIES_SENT leads whose requirements fit,
    and send them WhatsApp notifications.
    """
    import os
    import uuid
    from datetime import datetime, timezone
    from pymongo import MongoClient
    from apps.worker.tasks.whatsapp_tasks import send_whatsapp_message
    from services.matching.engine import calculate_base_structural_match_score, calculate_dynamic_property_confidence

    mongo_url = os.getenv("MONGO_URL") or os.getenv("MONGO_URI")
    client = MongoClient(mongo_url)
    db = client["nph_core"]

    try:
        # Find leads with MATCHABLE or PROPERTIES_SENT status
        leads = list(db["leads"].find({
            "status": {"$in": ["MATCHABLE", "PROPERTIES_SENT"]},
            "requirements.bhk": property_doc["bhk"],
            "requirements.listing_type": property_doc["listing_type"]
        }))

        logger.info(
            f"[Reverse Match] Checking {len(leads)} candidate leads "
            f"for property {property_doc['property_id']} ({property_doc['bhk']} BHK, {property_doc['area']})"
        )

        for lead in leads:
            reqs = lead.get("requirements", {})
            
            # 1. Area matching (case-insensitive substring containment)
            lead_area = reqs.get("area")
            prop_area = property_doc.get("area")
            if not lead_area or not prop_area:
                continue
            if lead_area.lower().strip() not in prop_area.lower().strip() and prop_area.lower().strip() not in lead_area.lower().strip():
                continue
                
            # 2. Price check
            max_price = reqs.get("max_price")
            prop_price = property_doc.get("price", 0)
            if max_price is not None and prop_price > max_price:
                continue

            # 3. Prevent duplicate notifications for the same property to this lead
            already_sent = db["recommendation_history"].find_one({
                "lead_id": lead["id"],
                "property_id": property_doc["property_id"]
            })
            if already_sent:
                logger.info(f"[Reverse Match] Lead {lead['id']} already notified of {property_doc['property_id']}. Skipping.")
                continue

            # 4. Calculate dynamic match score
            broker_phone = property_doc.get("broker_phone")
            broker_reliability = 100
            is_verified = False
            if broker_phone:
                broker = db["broker_profiles"].find_one({"_id": broker_phone})
                if broker:
                    broker_reliability = max(0, broker.get("reliability_score", 100))
                    is_verified = broker.get("verified", False)

            prop_scored = dict(property_doc)
            if is_verified and prop_scored.get("ownership_type", "broker") == "broker":
                prop_scored["ownership_type"] = "verified_broker"

            structural_score = calculate_base_structural_match_score(prop_scored, reqs)
            prop_confidence = calculate_dynamic_property_confidence(prop_scored)
            composite_score = structural_score + prop_confidence + broker_reliability

            # 5. Insert recommendation event
            recommendation = {
                "lead_id": lead["id"],
                "property_id": property_doc["property_id"],
                "score": composite_score,
                "sent_at": datetime.now(timezone.utc)
            }
            db["recommendation_history"].insert_one(recommendation)

            # 6. Save match block
            match_id = f"match_{uuid.uuid4().hex[:8]}"
            match_doc = {
                "match_id": match_id,
                "lead_id": lead["id"],
                "property_ids": [property_doc["property_id"]],
                "status": "SENT",
                "generated_at": datetime.now(timezone.utc)
            }
            db["matches"].insert_one(match_doc)

            # 7. Transition lead status to PROPERTIES_SENT and store last_properties_sent
            db["leads"].update_one(
                {"id": lead["id"]},
                {"$set": {
                    "status": "PROPERTIES_SENT",
                    "last_properties_sent": [property_doc["property_id"]],
                    "updated_at": datetime.now(timezone.utc)
                }}
            )

            # 8. Send WhatsApp notification
            deposit = property_doc.get("rental_details", {}).get("deposit", 0)
            if not deposit and "rental_details" not in property_doc:
                # If we queried a sparse property_doc, let's fetch deposit from DB
                full_prop = db["properties"].find_one({"property_id": property_doc["property_id"]})
                if full_prop:
                    deposit = full_prop.get("rental_details", {}).get("deposit", 0)

            reply_text = (
                f"🎉 Good news! A new matching property has just arrived:\n\n"
                f"*1. {property_doc.get('bhk')} BHK in {property_doc.get('area')}*\n"
                f"Rent: ₹{property_doc.get('price')} | Deposit: ₹{deposit}\n\n"
                f"Reply with '1' to book a site visit!"
            )
            
            logger.info(f"[Reverse Match] Notifying lead {lead['id']} of new property {property_doc['property_id']} with score {composite_score}")
            send_whatsapp_message.delay(lead["id"], reply_text)

            # 9. Record conversation history entry
            assistant_message = {
                "role": "assistant",
                "content": reply_text,
                "timestamp": datetime.now(timezone.utc)
            }
            db["conversations"].update_one(
                {"phone": lead["id"]},
                {
                    "$push": {"messages": assistant_message},
                    "$set": {"updated_at": datetime.now(timezone.utc)}
                },
                upsert=True
            )

    except Exception as err:
        logger.error(f"[Reverse Match] Error processing: {err}", exc_info=True)
        raise
    finally:
        client.close()
