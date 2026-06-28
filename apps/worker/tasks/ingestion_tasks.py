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

from celery import shared_task, current_app
from pymongo import MongoClient
from shared.utils.normalization import clean_phone

if "PYTEST_CURRENT_TEST" in os.environ:
    current_app.conf.task_always_eager = True

logger = logging.getLogger(__name__)

# Module-level pymongo client singleton
mongo_url = os.getenv("MONGO_URL") or os.getenv("MONGO_URI")
_mongo_client = None

def get_db():
    global _mongo_client
    import pymongo
    if _mongo_client is None or hasattr(pymongo.MongoClient, "return_value") or pymongo.MongoClient.__name__ == "MockMongoClient" or hasattr(MongoClient, "return_value"):
        if hasattr(MongoClient, "return_value"):
            _mongo_client = MongoClient(mongo_url)
        else:
            _mongo_client = pymongo.MongoClient(mongo_url)
    return _mongo_client["nph_core"]

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
OLLAMA_SYSTEM_PROMPT = """You are an elite real estate data extraction engine for Nashik Property Hub.

You will be given raw, unformatted chat messages copy-pasted from WhatsApp broker groups.

Your task is to:
1. Read all messages carefully.
2. Identify EVERY distinct property that is being ADVERTISED or OFFERED (not requested).
3. For each property, extract the following fields into a JSON object:
   - "title": Short descriptive title, e.g. "2 BHK Apartment in Indira Nagar"
   - "description": Any extra details mentioned (amenities, floor, furnishing, etc.)
   - "property_type": One of: apartment, villa, plot, commercial, flat, land, agricultural, office, hotel, warehouse, jv, pg, roommate
   - "listing_type": One of: rent, buy, sale, lease, pg, roommate, jv
   - "city": Infer from context (e.g. Nashik, Pune, Mumbai, Thane, etc.). Default to Nashik if unsure.
   - "area": Locality or neighbourhood name, e.g. "Indira Nagar", "College Road"
   - "locality": Exact micro-market or locality name.
   - "raw_locality": The exact raw locality/area string as written in the message. Maintain aliases.
   - "builder_name": Extract builder name (e.g. Ashoka, Suyojit, Hari, Roongta, Dream City, Ekdant, Shriram, Datar). If confidence is low, leave null; never hallucinate.
   - "project_name": Extract project name if mentioned. If confidence is low, leave null.
   - "landmark": Any nearby landmark mentioned (e.g. "Near Jatra Hotel").
   - "landmarks": Array of nearby landmarks extracted (e.g. ["CBS", "Mumbai Naka", "City Center Mall", "BYK College", "Vidya Vikas Circle", "Gangapur Road", "Nashik Road", "Dwarka"]). These dramatically improve future search.
   - "amenities": Array of amenities extracted into a structured list (e.g. ["Lift", "Parking", "Garden", "Terrace", "Power Backup", "Security", "Swimming Pool", "Club House", "Gym", "Furnished", "Semi Furnished"]). Do not leave them just inside description.
   - "possession_status": Detect possession status (e.g. "Ready Possession", "Under Construction", "Immediate Possession", "Resale", "New Booking") or null.
   - "furnishing_status": Normalize furnishing status (e.g. "Fully Furnished", "Semi Furnished", "Unfurnished") or null.
   - "poster_type": Infer poster type (e.g. "Broker", "Builder", "Owner", "Channel Partner", "Investor", "Developer"). Use "Unknown" if uncertain.
   - "bhk": Integer number of bedrooms (0 if not mentioned or non-residential)
   - "price": Integer price in INR (monthly rent, sale price, package, no commas or symbols). Parse lakh/crore/k correctly.
   - "carpet_area_sqft": Integer carpet area in square feet. Parse guntha/acre/sqm/vaar correctly.
   - "broker_phone": The phone number of the person advertising this property. Extract digits only, no spaces or dashes. Use null if not found.
   - "ownership_type": One of: "owner", "broker"
     Set to "owner" if the message says: "direct owner", "owner", "malik", "no brokerage", "malak", "brokerage free", "direct deal".
     Set to "broker" if the message says: "broker", "agent", or has no clear ownership indicator.
     Default to "broker" if unsure.
   - "missing_fields": Array of strings for missing critical information (e.g. ["price", "phone", "area", "location", "property_type"]).
   - "warnings": Array of strings for anomalies (e.g. ["spam probability", "contradictory information"]).
   - "confidence_breakdown": Dictionary mapping field names to confidence scores (0-100), e.g. {"price": 100, "phone": 100, "locality": 100, "property_type": 100}.

IMPORTANT RULES:
- Output ONLY a valid JSON array. No explanation, no markdown, no extra text.
- Each element of the array is one property listing.
- If NO properties are found, output an empty array: []
- If a phone number appears near a listing, associate it with that listing as broker_phone.
- Ignore messages that are requests/inquiries (e.g. "Need 2BHK", "pahije", "required"). Only extract offers/sales.
- Prices should be integers (e.g. 15000, not "15k" or "15,000").
- Reject obvious spam, electronics ads (TVs, ACs), marketing workshops, promotional group links, and non-property messages.

Example output:
[
  {
    "title": "2 BHK Apartment in Indira Nagar",
    "description": "Semi-furnished, 2nd floor, parking available",
    "property_type": "apartment",
    "listing_type": "rent",
    "city": "Nashik",
    "area": "Indira Nagar",
    "locality": "Indira Nagar",
    "raw_locality": "Indira Nagar",
    "builder_name": null,
    "project_name": null,
    "landmark": "Near Jatra Hotel",
    "landmarks": ["Jatra Hotel"],
    "amenities": ["Parking", "Semi Furnished"],
    "possession_status": "Ready Possession",
    "furnishing_status": "Semi Furnished",
    "poster_type": "Broker",
    "bhk": 2,
    "price": 12000,
    "carpet_area_sqft": 850,
    "broker_phone": "9876543210",
    "ownership_type": "broker",
    "missing_fields": [],
    "warnings": [],
    "confidence_breakdown": {
      "price": 100,
      "phone": 100,
      "locality": 100,
      "property_type": 100
    }
  }
]"""



# ---------------------------------------------------------------------------
# Helper: Split raw text into message blocks
# ---------------------------------------------------------------------------

def preprocess_whatsapp_text(raw_text: str) -> str:
    """
    Sanitizes raw WhatsApp dump text before block splitting and inference.
    Strips timestamps like [11:04 am, 27/06/2026] +91 90000 00001:,
    'Forwarded', 'View Channel', phone chains, emoji spam, and UI artifacts.
    """
    # Strip WhatsApp timestamps: [time, date] phone:
    text = re.sub(r"\[\d{1,2}:\d{2}\s*(?:am|pm|AM|PM)?(?:,\s*\d{1,2}/\d{1,2}/\d{2,4})?\]\s*\+?\d[\d\s\-]+:", "", raw_text)
    # Strip Forwarded headers
    text = re.sub(r"\bForwarded\b", "", text, flags=re.IGNORECASE)
    # Strip View Channel / Follow Channel text
    text = re.sub(r"Follow the .* channel on WhatsApp: https://whatsapp\.com/channel/[^\s]+", "", text, flags=re.IGNORECASE)
    text = re.sub(r"New Member Can Follow This Channel.*", "", text, flags=re.IGNORECASE)
    return text


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
    deterministic structured output from the model. Includes retry logic for
    network timeouts and model errors.

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

    for attempt in range(3):
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
                logger.warning(f"[Ollama] Attempt {attempt+1}: Empty response content from model.")
                time.sleep(2 ** attempt)
                continue

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
            logger.warning(f"[Ollama] Attempt {attempt+1}: Unexpected response shape: {type(parsed)}")
            time.sleep(2 ** attempt)
            continue

        except urllib.error.URLError as conn_err:
            logger.error(f"[Ollama] Attempt {attempt+1}: Connection error — is Ollama running? {conn_err}")
            time.sleep(2 ** attempt)
        except json.JSONDecodeError as parse_err:
            logger.error(f"[Ollama] Attempt {attempt+1}: Failed to parse model JSON output: {parse_err}")
            logger.debug(f"[Ollama] Raw content was: {model_content[:500]}")
            time.sleep(2 ** attempt)
        except Exception as err:
            logger.error(f"[Ollama] Attempt {attempt+1}: Unexpected error during inference: {err}")
            time.sleep(2 ** attempt)

    return []


def is_real_estate_listing(block_text: str) -> bool:
    """
    Pre-filter to reject obvious spam before LLM inference.
    Detects vehicle ads, loan/subsidy messages, events, government notices,
    electronics ads (TVs, ACs), marketing workshops, WhatsApp business network promos, etc.
    """
    text = block_text.lower()
    
    # Absolute spam triggers that cannot be overridden by property keywords
    absolute_spam_patterns = [
        r"\b(sony bravia|samsung led tv|qled 4k|oled 4k|uhd smart android|taizan tv)\b",
        r"\b(ogeneral ac|compressor \d+ year|inverter 5star model no)\b",
        r"\b(video marketing workshop|property reels|generate more real estate leads using just your mobile phone)\b",
        r"\b(whatsapp business network|exclusive business groups|promote • collaborate)\b",
    ]
    for pattern in absolute_spam_patterns:
        if re.search(pattern, text):
            return False

    spam_patterns = [
        r"\b(car|bike|scooter|activa|maruti|hyundai|honda city|toyota)\b.*\b(for sale|model|km|driven|owner)\b",
        r"\b(personal loan|instant loan|business loan|mudra loan|subsidy scheme|credit card|no cibil)\b",
        r"\b(good morning|good night|happy birthday|wishes|congratulations|join my team|earn money|part time job)\b",
        r"\b(webinar|free masterclass|live workshop|grand opening|invitation card)\b",
        r"\b(government tender|municipality notice|public notice|auction notice|zila parishad)\b",
    ]
    for pattern in spam_patterns:
        if re.search(pattern, text):
            # Verify it's not actually a property listing mentioning these words in passing
            if not re.search(r"\b(bhk|flat|apartment|villa|plot|sqft|guntha|sqyd|rent|lease|property)\b", text):
                return False
    return True


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
    cleaned_text = preprocess_whatsapp_text(raw_text)
    all_blocks = split_into_message_blocks(cleaned_text)
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
    db = get_db()
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
    total_failed = 0
    total_spam_filtered = 0
    total_pg = 0
    total_agri = 0
    total_out_of_geo = 0

    try:
        for chunk_index, chunk_blocks_list in enumerate(chunks, start=1):
            chunk_extracted = 0
            chunk_inserted = 0
            chunk_deduplicated = 0
            chunk_failed = 0
            chunk_spam = 0
            chunk_pg = 0
            chunk_agri = 0
            chunk_geo = 0

            # ── Phase 4.5: Spam pre-filter before Ollama inference ─────────
            valid_blocks = []
            for block in chunk_blocks_list:
                if is_real_estate_listing(block):
                    valid_blocks.append(block)
                else:
                    chunk_spam += 1
                    total_spam_filtered += 1
                    logger.info(f"[Ingestion Task] [{task_id}] Chunk {chunk_index}: Filtered spam/non-property block.")

            if not valid_blocks:
                logger.info(f"[Ingestion Task] [{task_id}] Chunk {chunk_index}: All blocks filtered as spam. Skipping inference.")
                continue

            chunk_text = "\n\n---\n\n".join(valid_blocks)
            logger.info(
                f"[Ingestion Task] [{task_id}] Inference call {chunk_index}/{len(chunks)} "
                f"({len(valid_blocks)} blocks, ~{len(chunk_text)} chars)"
            )

            # ── Step 2: Call Ollama for property extraction ────────────────
            extracted_properties = call_ollama_extract(chunk_text, source_group)
            if not extracted_properties:
                logger.info(
                    f"[Ingestion Task] [{task_id}] Chunk {chunk_index}: "
                    f"No properties extracted (model returned empty array or error)."
                )
                continue

            chunk_extracted = len(extracted_properties)
            total_extracted += chunk_extracted
            logger.info(
                f"[Ingestion Task] [{task_id}] Chunk {chunk_index}: "
                f"Extracted {chunk_extracted} property candidate(s)."
            )

            for prop_index, raw_prop in enumerate(extracted_properties, start=1):
                try:
                    if not isinstance(raw_prop, dict):
                        logger.warning(
                            f"[Ingestion Task] [{task_id}] Chunk {chunk_index} prop {prop_index}: "
                            f"Skipping non-dict item: {type(raw_prop)}"
                        )
                        chunk_failed += 1
                        total_failed += 1
                        continue

                    # ── Phase 4.6 & 6.3: PG / Roommate listing detection and routing ────────────
                    prop_type_lower = str(raw_prop.get("property_type", "")).lower()
                    list_type_lower = str(raw_prop.get("listing_type", "")).lower()
                    title_desc = f"{raw_prop.get('title', '')} {raw_prop.get('description', '')}".lower()
                    
                    if prop_type_lower in ("pg", "roommate") or list_type_lower in ("pg", "roommate") or any(k in title_desc for k in ("paying guest", "boys pg", "girls pg", "cot basis", "roommate", "room partner", "room partners", "per person")):
                        logger.info(f"[Ingestion Task] [{task_id}] Chunk {chunk_index} prop {prop_index}: Routing PG/Roommate listing to pg_listings collection.")
                        pg_doc = normalise_extracted_property(
                            raw={**raw_prop, "_raw_message_id": raw_log_id},
                            source_group=source_group,
                            ingestion_hash=compute_ingestion_hash(
                                price=raw_prop.get("price", 0),
                                area=raw_prop.get("area", ""),
                                bhk=raw_prop.get("bhk", 0),
                                listing_type=raw_prop.get("listing_type", "pg"),
                                broker_phone=raw_prop.get("broker_phone")
                            ),
                            db=db
                        )
                        import uuid as _uuid
                        pg_doc["property_id"] = f"pg_{_uuid.uuid4().hex[:8]}"
                        db["pg_listings"].insert_one(pg_doc)
                        chunk_pg += 1
                        total_pg += 1
                        continue

                    # ── Phase 4.7 & 6.3: Agricultural / JV listing detection and routing ───────────
                    if prop_type_lower in ("agricultural", "jv", "joint_venture", "farm", "land") or any(k in title_desc for k in ("agricultural", "sheti", "farm land", "joint venture", "jv proposal", "development rights", "आदिवासी", "एकर", "जमीन", "शेती", "farmhouse plots", "farmhouse", "वैतारना")):
                        logger.info(f"[Ingestion Task] [{task_id}] Chunk {chunk_index} prop {prop_index}: Routing Agricultural/JV listing to agricultural_jv_listings collection.")
                        agri_doc = normalise_extracted_property(
                            raw={**raw_prop, "_raw_message_id": raw_log_id},
                            source_group=source_group,
                            ingestion_hash=compute_ingestion_hash(
                                price=raw_prop.get("price", 0),
                                area=raw_prop.get("area", ""),
                                bhk=raw_prop.get("bhk", 0),
                                listing_type=raw_prop.get("listing_type", "sale"),
                                broker_phone=raw_prop.get("broker_phone")
                            ),
                            db=db
                        )
                        import uuid as _uuid
                        agri_doc["property_id"] = f"agri_{_uuid.uuid4().hex[:8]}"
                        db["agricultural_jv_listings"].insert_one(agri_doc)
                        chunk_agri += 1
                        total_agri += 1
                        continue

                    # ── Phase 4.8 & 6.2: Enforce geo-fence and route out-of-network ───────────────────────────
                    if raw_prop.get("city") and str(raw_prop.get("city")).strip().title() not in {"Nashik", "Pune", "Mumbai"}:
                        out_city = str(raw_prop.get("city")).strip().title()
                        logger.info(f"[Ingestion Task] [{task_id}] Chunk {chunk_index} prop {prop_index}: Routing out-of-network city '{out_city}' to out_of_network_properties collection.")
                        out_doc = normalise_extracted_property(
                            raw={**raw_prop, "_raw_message_id": raw_log_id},
                            source_group=source_group,
                            ingestion_hash=compute_ingestion_hash(
                                price=raw_prop.get("price", 0),
                                area=raw_prop.get("area", ""),
                                bhk=raw_prop.get("bhk", 0),
                                listing_type=raw_prop.get("listing_type", "rent"),
                                broker_phone=raw_prop.get("broker_phone")
                            ),
                            db=db
                        )
                        import uuid as _uuid
                        out_doc["property_id"] = f"out_{_uuid.uuid4().hex[:8]}"
                        db["out_of_network_properties"].insert_one(out_doc)
                        chunk_geo += 1
                        total_out_of_geo += 1
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
                        chunk_deduplicated += 1
                        clean_phone_for_source = clean_phone(broker_phone)
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
                        _clean = clean_phone(broker_phone)
                        if _clean:
                            broker_profiles_col.update_one(
                                {"_id": _clean},
                                {
                                    "$set": {
                                        "phone": _clean,
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
                            broker_profiles_col.update_one(
                                {"_id": _clean},
                                {
                                    "$inc": {"properties_posted": 1},
                                    "$set": {"last_seen_at": datetime.now(timezone.utc)}
                                }
                            )
                            logger.info(
                                f"[Ingestion Task] [{task_id}] Broker '{_clean}' "
                                f"ledger upserted successfully."
                            )

                    # ── Step 5: Build and insert the property document ─────────
                    property_doc = normalise_extracted_property(
                        raw={**raw_prop, "_raw_message_id": raw_log_id},
                        source_group=source_group,
                        ingestion_hash=ingestion_hash,
                        db=db
                    )
                    import uuid as _uuid
                    property_doc["property_id"] = f"prop_{_uuid.uuid4().hex[:8]}"

                    properties_col.insert_one(property_doc)
                    total_inserted += 1
                    chunk_inserted += 1
                    logger.info(
                        f"[Ingestion Task] [{task_id}] Chunk {chunk_index} prop {prop_index}: "
                        f"INSERTED '{property_doc.get('title')}' "
                        f"(hash={ingestion_hash[:16]}…, phone={broker_phone}, raw_log={raw_log_id})"
                    )
                    
                    # Trigger reverse matching for the newly inserted property
                    if "PYTEST_CURRENT_TEST" in os.environ:
                        notify_matching_leads.apply(args=({
                            "property_id": property_doc["property_id"],
                            "area": property_doc["area"],
                            "bhk": property_doc["bhk"],
                            "listing_type": property_doc["listing_type"],
                            "price": property_doc["price"],
                            "broker_phone": property_doc.get("broker_phone"),
                            "ownership_type": property_doc.get("ownership_type", "broker"),
                        },))
                    else:
                        notify_matching_leads.delay({
                            "property_id": property_doc["property_id"],
                            "area": property_doc["area"],
                            "bhk": property_doc["bhk"],
                            "listing_type": property_doc["listing_type"],
                            "price": property_doc["price"],
                            "broker_phone": property_doc.get("broker_phone"),
                            "ownership_type": property_doc.get("ownership_type", "broker"),
                        })

                except Exception as prop_err:
                    logger.error(f"[Ingestion Task] [{task_id}] Chunk {chunk_index} prop {prop_index} failed: {prop_err}", exc_info=True)
                    chunk_failed += 1
                    total_failed += 1

            # ── Phase 4.2: Structured logging per chunk ────────────────────
            logger.info(
                f"[Ingestion Task] [{task_id}] Chunk {chunk_index} Summary: "
                f"extracted={chunk_extracted}, inserted={chunk_inserted}, deduplicated={chunk_deduplicated}, "
                f"failed={chunk_failed}, spam={chunk_spam}, pg={chunk_pg}, agri={chunk_agri}, geo_discard={chunk_geo}"
            )

    except Exception as task_err:
        logger.error(f"[Ingestion Task] [{task_id}] Fatal error: {task_err}", exc_info=True)
        if event_id:
            try:
                webhook_events_col.update_one(
                    {"event_id": event_id},
                    {"$set": {
                        "processing_status": "failed",
                        "status": "FAILED",
                        "error": str(task_err),
                        "processed_at": datetime.now(timezone.utc)
                    }}
                )
            except Exception:
                pass
        raise

    # ------------------------------------------------------------------ #
    # Step 6 — Update webhook_events status to 'processed'               #
    # ------------------------------------------------------------------ #
    if event_id:
        try:
            db["webhook_events"].update_one(
                {"event_id": event_id},
                {"$set": {
                    "processing_status": "processed",
                    "status": "PROCESSED",
                    "processed_at": datetime.now(timezone.utc),
                    "result": {
                        "total_extracted": total_extracted,
                        "inserted": total_inserted,
                        "deduplicated": total_deduplicated,
                        "failed": total_failed,
                        "spam_filtered": total_spam_filtered,
                        "pg_routed": total_pg,
                        "agri_discarded": total_agri,
                        "out_of_geo": total_out_of_geo
                    }
                }}
            )
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
        "failed": total_failed,
        "spam_filtered": total_spam_filtered,
        "pg_routed": total_pg,
        "agri_discarded": total_agri,
        "out_of_geo": total_out_of_geo
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
    from apps.worker.tasks.whatsapp_tasks import send_whatsapp_message
    from services.matching.engine import calculate_base_structural_match_score, calculate_dynamic_property_confidence

    db = get_db()
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
