import re
import hashlib
from datetime import datetime, timezone
from typing import Dict, Any, Optional

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


def clean_phone(value: Any) -> Optional[str]:
    """Cleans a phone number to standard 10-digit format, handling country codes."""
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

    # Validate and normalise enumerated string fields
    valid_property_types = {"apartment", "villa", "plot", "commercial", "flat", "land"}
    valid_listing_types = {"rent", "buy", "sale"}
    valid_cities = {"Nashik", "Pune", "Mumbai"}
    valid_ownership_types = {"owner", "verified_broker", "broker"}

    property_type = clean_str(raw.get("property_type"), "apartment").lower()
    if property_type not in valid_property_types:
        property_type = "apartment"

    listing_type = clean_str(raw.get("listing_type"), "rent").lower()
    if listing_type not in valid_listing_types:
        listing_type = "rent"

    city = clean_str(raw.get("city"), "Nashik").strip().title()
    if city not in valid_cities:
        city = "Nashik"

    # Ownership type — extracted by LLM or defaulted to "broker"
    ownership_type = clean_str(raw.get("ownership_type"), "broker").lower()
    if ownership_type not in valid_ownership_types:
        ownership_type = "broker"

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

        # Ownership type — owner > verified_broker > broker
        # Used by search/matching scoring to rank direct owner listings higher.
        "ownership_type": ownership_type,

        # Source metadata sub-document (primary origination, legacy compat)
        "source": {
            "type": "owner_network" if ownership_type == "owner" else "broker_group",
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
