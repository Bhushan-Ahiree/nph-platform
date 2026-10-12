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
    try:
        price_val = str(int(float(price))) if price else "0"
    except (ValueError, TypeError):
        val_str = str(price).strip().lower()
        val_str = re.sub(r"(?:rs\.?|inr|rupees?|monthly|per\s*person|per\s*month|per\s*guntha|per\s*vaar|per\s*sqft|per\s*acre|प्रति|\s)", "", val_str)
        val_str = val_str.replace(",", "")
        try:
            match = re.search(r"^([0-9.]+)(lakhs?|lacs?|crores?|crs?|k|thousand|लाख|कोटी|हजार)?$", val_str)
            if match:
                num = float(match.group(1))
                unit = match.group(2)
                if unit in ("lakh", "lakhs", "lac", "lacs", "लाख"):
                    price_val = str(int(num * 100000))
                elif unit in ("crore", "crores", "cr", "crs", "कोटी"):
                    price_val = str(int(num * 10000000))
                elif unit in ("k", "thousand", "हजार"):
                    price_val = str(int(num * 1000))
                else:
                    price_val = str(int(num))
            else:
                price_val = str(int(float(val_str)))
        except (ValueError, TypeError):
            price_val = "0"
    price_clean = alphanumeric_only(price_val)
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



def resolve_canonical_locality(raw_locality: Any) -> str:
    """
    Canonical locality resolver.
    Maintains aliases and resolves messy locality strings to canonical names.
    Never overwrites raw data; returns the canonical locality.
    """
    if not raw_locality:
        return "Unknown"
    s = str(raw_locality).strip()
    clean = s.lower().replace(" ", "").replace(".", "")
    
    # Check specific aliases and patterns
    if any(alias in clean for alias in ("gangapurroad", "gangapurrd", "gangapuroad", "gangapur")):
        return "Gangapur Road"
    if any(clean.startswith(alias) or clean == alias for alias in ("pathardiphata", "pathardigaon", "pathardi")):
        return "Pathardi"
    if any(alias in clean for alias in ("collegeroad", "collegerd")):
        return "College Road"
    if any(alias in clean for alias in ("indiranagar", "indranagar")):
        return "Indira Nagar"
    if any(alias in clean for alias in ("mahatmanagar", "mahatamnagar")):
        return "Mahatma Nagar"
    if any(alias in clean for alias in ("govindnagar", "govindnagar")):
        return "Govind Nagar"
    if any(alias in clean for alias in ("nashikroad", "nasikroad", "nashikrd", "nasikrd")):
        return "Nashik Road"
    if any(alias in clean for alias in ("mumbainaka", "mumbainaka")):
        return "Mumbai Naka"
    if any(alias in clean for alias in ("citycenter", "ccm", "citycentermall")):
        return "City Center Mall"
    if any(alias in clean for alias in ("dwarka", "dwarkacircle")):
        return "Dwarka"
    if any(alias in clean for alias in ("cbs", "cbscircle")):
        return "CBS"
    if any(alias in clean for alias in ("bykcollege", "byk")):
        return "BYK College"
    if any(alias in clean for alias in ("vidyavikas", "vidyavikascircle")):
        return "Vidya Vikas Circle"
    
    return s


def normalise_extracted_property(
    raw: Dict[str, Any],
    source_group: str,
    ingestion_hash: str,
    db: Any = None
) -> Dict[str, Any]:
    """
    Converts a raw dict from Ollama's JSON output into a clean property document
    ready for insertion into the 'properties' MongoDB collection.

    Maps all fields to the PropertySchemaV2 flat-field layout used by the platform.
    Applies all required defaults mandated by the ingestion pipeline specification.
    Includes Sprint H Knowledge Graph entity linking and resolution.

    Args:
        raw: The raw property dict from the model's JSON array.
        source_group: WhatsApp group name for the 'source' sub-document.
        ingestion_hash: Pre-computed SHA-256 hash for deduplication.
        db: Optional MongoDB database client handle for Knowledge Graph resolution.

    Returns:
        Clean property dict ready for property_repo.upsert_property().
    """
    def safe_int(value: Any, default: int = 0) -> int:
        try:
            return int(float(str(value).replace(",", "").replace("k", "000").replace("K", "000")))
        except (ValueError, TypeError):
            return default

    def safe_price(value: Any, default: int = 0) -> int:
        if value is None:
            return default
        if isinstance(value, (int, float)):
            return int(value)
        val_str = str(value).strip().lower()
        val_str = re.sub(r"(?:rs\.?|inr|rupees?|monthly|per\s*person|per\s*month|per\s*guntha|per\s*vaar|per\s*sqft|per\s*acre|प्रति|\s)", "", val_str)
        val_str = val_str.replace(",", "")
        try:
            match = re.search(r"^([0-9.]+)(lakhs?|lacs?|crores?|crs?|k|thousand|लाख|कोटी|हजार)?$", val_str)
            if match:
                num = float(match.group(1))
                unit = match.group(2)
                if unit in ("lakh", "lakhs", "lac", "lacs", "लाख"):
                    return int(num * 100000)
                elif unit in ("crore", "crores", "cr", "crs", "कोटी"):
                    return int(num * 10000000)
                elif unit in ("k", "thousand", "हजार"):
                    return int(num * 1000)
                return int(num)
            return int(float(val_str))
        except (ValueError, TypeError):
            return default

    def safe_area(value: Any, default: Optional[int] = None) -> Optional[int]:
        if value is None:
            return default
        if isinstance(value, (int, float)):
            return int(value)
        val_str = str(value).strip().lower()
        val_str = val_str.replace(",", "").replace(" ", "")
        try:
            match = re.search(r"^([0-9.]+)(gunthas?|gunthe|guntas?|vaars?|wars?|sqyds?|sqyards?|sqfts?|sqft|sqmeters?|sqm|acres?|एकर|गुंठे|गुंठा|वार|वारा)?$", val_str)
            if match:
                num = float(match.group(1))
                unit = match.group(2)
                if unit in ("guntha", "gunthas", "gunthe", "gunta", "guntas", "गुंठे", "गुंठा"):
                    return int(num * 1089)
                elif unit in ("vaar", "vaars", "war", "wars", "sqyd", "sqyds", "sqyard", "sqyards", "वार", "वारा"):
                    return int(num * 9)
                elif unit in ("sqmeter", "sqmeters", "sqm"):
                    return int(num * 10.7639)
                elif unit in ("acre", "acres", "एकर"):
                    return int(num * 43560)
                return int(num)
            return int(float(val_str))
        except (ValueError, TypeError):
            return default

    def clean_str(value: Any, default: str = "") -> str:
        if value is None:
            return default
        return str(value).strip()

    # Validate and normalise enumerated string fields
    valid_property_types = {"apartment", "villa", "plot", "commercial", "flat", "land", "agricultural", "office", "hotel", "warehouse", "jv", "pg", "roommate"}
    valid_listing_types = {"rent", "buy", "sale", "lease", "pg", "roommate", "jv"}
    valid_ownership_types = {"owner", "verified_broker", "broker"}

    property_type = clean_str(raw.get("property_type"), "apartment").lower()
    if property_type not in valid_property_types:
        property_type = "apartment"

    listing_type = clean_str(raw.get("listing_type"), "rent").lower()
    if listing_type not in valid_listing_types:
        listing_type = "rent"

    city = clean_str(raw.get("city"), "Nashik").strip().title()

    # Ownership type — extracted by LLM or defaulted to "broker"
    ownership_type = clean_str(raw.get("ownership_type"), "broker").lower()
    if ownership_type not in valid_ownership_types:
        ownership_type = "broker"

    broker_phone = clean_phone(raw.get("broker_phone"))
    now = datetime.now(timezone.utc)
    price_val = safe_price(raw.get("price"), 0)
    area_val = safe_area(raw.get("carpet_area_sqft") or raw.get("area_sqft") or raw.get("sqft") or raw.get("area_value"))
    bhk_val = safe_int(raw.get("bhk"), 0)

    raw_text = raw.get("raw_text") or raw.get("_raw_text") or ""
    if raw_text:
        from shared.utils.deterministic_parser import CategoryAExtractor
        det_intent = CategoryAExtractor.detect_intent(raw_text)
        det_price_info = CategoryAExtractor.extract_price(raw_text)
        det_area_info = CategoryAExtractor.extract_area(raw_text)
        det_bhk_info = CategoryAExtractor.extract_bhk(raw_text)
        det_phone = CategoryAExtractor.extract_phone(raw_text)

        if det_price_info["price"] > 0:
            price_val = det_price_info["price"]
        if det_area_info["carpet_area_sqft"] is not None:
            area_val = det_area_info["carpet_area_sqft"]
        if det_bhk_info["bhk"] > 0:
            bhk_val = det_bhk_info["bhk"]
        if det_phone:
            broker_phone = clean_phone(det_phone)
        if det_intent["listing_type"] in ("sale", "lease", "rent"):
            listing_type = det_intent["listing_type"]
        if det_intent["property_type"] in ("land", "plot", "commercial", "villa", "apartment"):
            property_type = det_intent["property_type"]

    # Sprint G: Locality Intelligence
    raw_locality = clean_str(raw.get("raw_locality") or raw.get("locality") or raw.get("area"), "Unknown")
    canonical_locality = resolve_canonical_locality(raw_locality)
    
    # Sprint G: Builder Intelligence
    builder_name = clean_str(raw.get("builder_name")) or None
    project_name = clean_str(raw.get("project_name")) or None
    
    # Sprint G: Landmark Extraction
    landmarks = [clean_str(item) for item in raw.get("landmarks", []) if clean_str(item)] if isinstance(raw.get("landmarks"), list) else []
    if not landmarks and clean_str(raw.get("landmark")):
        landmarks.append(clean_str(raw.get("landmark")))

    # Sprint G: Amenity Extraction
    amenities = [clean_str(a) for a in raw.get("amenities", []) if clean_str(a)] if isinstance(raw.get("amenities"), list) else []

    # Sprint G: Possession Status
    raw_poss = clean_str(raw.get("possession_status")).lower()
    possession_status = None
    if any(k in raw_poss for k in ("ready", "ready possession")):
        possession_status = "Ready Possession"
    elif any(k in raw_poss for k in ("under construction", "construction", "uc")):
        possession_status = "Under Construction"
    elif any(k in raw_poss for k in ("immediate", "immediate possession")):
        possession_status = "Immediate Possession"
    elif any(k in raw_poss for k in ("resale",)):
        possession_status = "Resale"
    elif any(k in raw_poss for k in ("new booking", "new")):
        possession_status = "New Booking"
    elif raw.get("possession_status"):
        possession_status = clean_str(raw.get("possession_status"))

    # Sprint G: Furnishing Intelligence
    raw_furn = clean_str(raw.get("furnishing_status") or raw.get("furnishing")).lower()
    furnishing_status = None
    rental_furnishing = "unfurnished"
    if any(k in raw_furn for k in ("fully", "fully furnished", "full")):
        furnishing_status = "Fully Furnished"
        rental_furnishing = "fully-furnished"
    elif any(k in raw_furn for k in ("semi", "semi furnished", "partial")):
        furnishing_status = "Semi Furnished"
        rental_furnishing = "semi-furnished"
    elif any(k in raw_furn for k in ("unfurnished", "none", "no")):
        furnishing_status = "Unfurnished"
        rental_furnishing = "unfurnished"
    elif raw.get("furnishing_status"):
        furnishing_status = clean_str(raw.get("furnishing_status"))

    # Sprint G: Broker Classification
    raw_poster = clean_str(raw.get("poster_type") or raw.get("ownership_type")).lower()
    poster_type = "Unknown"
    if any(k in raw_poster for k in ("channel partner", "cp")):
        poster_type = "Channel Partner"
    elif any(k in raw_poster for k in ("developer",)):
        poster_type = "Developer"
    elif any(k in raw_poster for k in ("builder",)):
        poster_type = "Builder"
    elif any(k in raw_poster for k in ("investor",)):
        poster_type = "Investor"
    elif any(k in raw_poster for k in ("owner", "malik", "malak", "direct")):
        poster_type = "Owner"
    elif any(k in raw_poster for k in ("broker", "agent", "verified_broker")):
        poster_type = "Broker"
    elif raw.get("poster_type"):
        poster_type = clean_str(raw.get("poster_type"), "Unknown")

    # Sprint G: Extraction Diagnostics & Listing Confidence
    missing_fields = list(raw.get("missing_fields", [])) if isinstance(raw.get("missing_fields"), list) else []
    warnings = list(raw.get("warnings", [])) if isinstance(raw.get("warnings"), list) else []
    confidence_breakdown = dict(raw.get("confidence_breakdown", {})) if isinstance(raw.get("confidence_breakdown"), dict) else {}

    if not price_val:
        if "price" not in missing_fields: missing_fields.append("price")
    if not broker_phone:
        if "phone" not in missing_fields: missing_fields.append("phone")
    if not area_val:
        if "area" not in missing_fields: missing_fields.append("area")
    if raw_locality == "Unknown" and clean_str(raw.get("area"), "Unknown") == "Unknown":
        if "location" not in missing_fields: missing_fields.append("location")
    if not raw.get("property_type"):
        if "property_type" not in missing_fields: missing_fields.append("property_type")

    if price_val > 0 and price_val < 1000 and listing_type in ("buy", "sale", "jv"):
        if "contradictory information" not in warnings: warnings.append("contradictory information")
    if price_val > 100000000 and listing_type in ("rent", "pg", "roommate"):
        if "contradictory information" not in warnings: warnings.append("contradictory information")

    base_score = 100
    if "price" in missing_fields: base_score -= 25
    if "phone" in missing_fields: base_score -= 20
    if "area" in missing_fields: base_score -= 15
    if "location" in missing_fields: base_score -= 20
    if "property_type" in missing_fields: base_score -= 10
    
    for w in warnings:
        if "spam" in w.lower(): base_score -= 30
        elif "contradictory" in w.lower(): base_score -= 20
        else: base_score -= 10

    listing_quality_score = max(0, min(100, base_score))

    if not confidence_breakdown:
        confidence_breakdown = {
            "price": 100 if price_val else 0,
            "phone": 100 if broker_phone else 0,
            "locality": 100 if raw_locality != "Unknown" else 0,
            "property_type": 100 if raw.get("property_type") else 50,
            "overall": listing_quality_score
        }

    # ── Sprint H: Knowledge Graph Entity Resolution & Linking ────────────────
    locality_id = None
    builder_id = None
    project_id = None
    amenity_ids = []

    if db is not None:
        import uuid
        # 1. Locality Resolution
        if raw_locality and raw_locality != "Unknown":
            loc_col = db["localities"]
            loc_match = loc_col.find_one({"city": city, "aliases": raw_locality.lower().strip()})
            if loc_match:
                locality_id = loc_match.get("locality_id")
                canonical_locality = loc_match.get("canonical_name")
            else:
                locality_id = f"loc_{city.lower()[:3]}_{uuid.uuid4().hex[:6]}"
                try:
                    loc_col.insert_one({
                        "_id": locality_id,
                        "locality_id": locality_id,
                        "city": city,
                        "canonical_name": canonical_locality,
                        "aliases": [raw_locality.lower().strip(), canonical_locality.lower().strip()],
                        "micro_market": f"{city} Core",
                        "pin_codes": [],
                        "active_properties_count": 1,
                        "created_at": now,
                        "updated_at": now
                    })
                except Exception:
                    pass

        # 2. Builder Resolution
        if builder_name:
            bld_col = db["builders"]
            bld_match = bld_col.find_one({"city": city, "aliases": builder_name.lower().strip()})
            if bld_match:
                builder_id = bld_match.get("builder_id")
                builder_name = bld_match.get("canonical_name")
            else:
                builder_id = f"bldr_{uuid.uuid4().hex[:8]}"
                try:
                    bld_col.insert_one({
                        "_id": builder_id,
                        "builder_id": builder_id,
                        "canonical_name": builder_name,
                        "aliases": [builder_name.lower().strip()],
                        "city": city,
                        "reputation_score": 100,
                        "active_projects_count": 1,
                        "total_projects_count": 1,
                        "verified": False,
                        "created_at": now,
                        "updated_at": now
                    })
                except Exception:
                    pass

        # 3. Project Resolution
        if project_name:
            prj_col = db["projects"]
            prj_match = prj_col.find_one({"city": city, "aliases": project_name.lower().strip()})
            if prj_match:
                project_id = prj_match.get("project_id")
                project_name = prj_match.get("canonical_name")
                if not builder_id and prj_match.get("builder_id"):
                    builder_id = prj_match.get("builder_id")
            else:
                project_id = f"proj_{uuid.uuid4().hex[:8]}"
                try:
                    prj_col.insert_one({
                        "_id": project_id,
                        "project_id": project_id,
                        "builder_id": builder_id,
                        "canonical_name": project_name,
                        "aliases": [project_name.lower().strip()],
                        "locality_id": locality_id,
                        "city": city,
                        "possession_status": possession_status,
                        "master_amenities": amenities,
                        "active_properties_count": 1,
                        "created_at": now,
                        "updated_at": now
                    })
                except Exception:
                    pass

        # 4. Amenity Normalization
        if amenities:
            amen_col = db["amenity_dictionary"]
            for a in amenities:
                a_clean = a.lower().strip()
                amen_match = amen_col.find_one({"aliases": a_clean})
                if amen_match:
                    amenity_ids.append(amen_match.get("amenity_id"))
                else:
                    slug = re.sub(r"[^a-z0-9]", "_", a_clean)
                    aid = f"amen_{slug[:15]}"
                    try:
                        amen_col.insert_one({
                            "_id": aid,
                            "amenity_id": aid,
                            "canonical_name": a_clean,
                            "display_name": a.strip().title(),
                            "category": "general",
                            "aliases": [a_clean],
                            "weight": 10
                        })
                        amenity_ids.append(aid)
                    except Exception:
                        amenity_ids.append(aid)

    return {
        # Core PropertySchemaV2 fields
        "title": clean_str(raw.get("title"), "Property Listing"),
        "description": clean_str(raw.get("description")),
        "property_type": property_type,
        "listing_type": listing_type,
        "city": city,
        "area": clean_str(raw.get("area"), "Unknown"),
        "locality": raw_locality,
        "raw_locality": raw_locality,
        "canonical_locality": canonical_locality,
        "builder_name": builder_name,
        "project_name": project_name,
        "landmark": clean_str(raw.get("landmark"), ""),
        "landmarks": landmarks,
        "amenities": amenities,
        "possession_status": possession_status,
        "furnishing_status": furnishing_status,
        "poster_type": poster_type,
        "listing_quality_score": listing_quality_score,
        "missing_fields": missing_fields,
        "warnings": warnings,
        "confidence_breakdown": confidence_breakdown,
        "bhk": bhk_val,
        "price": price_val,
        "normalized_price_inr": price_val,
        "parking": False,
        "carpet_area_sqft": area_val,
        "normalized_area_sqft": area_val,

        # Sprint H Knowledge Graph foreign keys
        "locality_id": locality_id,
        "builder_id": builder_id,
        "project_id": project_id,
        "amenity_ids": amenity_ids,

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
        "raw_text": raw_text,

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
            "furnishing": rental_furnishing
        },
        "intelligence": {
            "hot_property": False,
            "duplicate_count": 0,
            "source_confidence": 100
        },
    }

