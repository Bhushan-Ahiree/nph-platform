import re
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional, Tuple
from shared.utils.deterministic_parser import CategoryAExtractor

# --- CONFIGURATION CONSTANTS ---
MIN_RENT_PRICE = 500
MAX_RENT_PRICE = 500000  # 5 Lakhs
MIN_SALE_PRICE = 100000  # 1 Lakh
MAX_SALE_PRICE = 500000000  # 50 Crores

KNOWN_GROUP_PATTERNS = [
    r"कान्हादेश/कसमादे\s*\(?\s*नाशिक\s*\)?.*",
    r"real estate.*nashik",
    r"property.*nashik",
]

KNOWN_REQUIREMENT_KEYWORDS = [
    "पाहिजे", "wanted", "looking for", "need", "requirement", "required", 
    "searching", "buy requirement", "rent requirement"
]

KNOWN_METADATA_HEADERS = [
    "forwarded", "forwarded message"
]

@dataclass
class ValidationResult:
    passed: bool
    repaired: bool = False
    warnings: List[str] = field(default_factory=list)
    penalties: List[str] = field(default_factory=list)
    updated_value: Any = None

def _clean_phone_for_comparison(phone: str) -> str:
    if not phone:
        return ""
    # Strip everything except digits
    return re.sub(r"\D", "", str(phone))

def validate_title(title: str, phone: str, intent: Dict[str, Any]) -> ValidationResult:
    if not title:
        return ValidationResult(passed=False, warnings=["Title is empty"])
        
    title_clean = title.strip()
    
    # Reject empty titles
    if not title_clean or title_clean.lower() == "property listing":
        return ValidationResult(passed=False, warnings=["Title is empty or generic placeholder"])

    # Reject if it's just "contact"
    if title_clean.lower() == "contact" or title_clean.lower() == "contact:":
        return ValidationResult(passed=False, warnings=["Title is just 'contact'"])

    # Reject if only punctuation or emojis
    if re.fullmatch(r"[^\w\s]+", title_clean):
        return ValidationResult(passed=False, warnings=["Title contains only punctuation or emojis"])

    # Reject if title is just the phone number
    title_digits = re.sub(r"\D", "", title_clean)
    if phone and title_digits and title_digits in _clean_phone_for_comparison(phone):
        if len(title_digits) >= 8: # Arbitrary reasonable length for phone
            return ValidationResult(passed=False, warnings=["Title is just the phone number"])
            
    # Same check if it says "Contact: XXXXX"
    if title_clean.lower().startswith("contact:") or title_clean.lower().startswith("contact "):
        num_part = re.sub(r"\D", "", title_clean)
        if len(num_part) >= 8:
            return ValidationResult(passed=False, warnings=["Title is a contact number"])

    return ValidationResult(passed=True, updated_value=title_clean)

def validate_price(price: int, phone: str, listing_type: str) -> ValidationResult:
    if not isinstance(price, (int, float)):
        try:
            price = int(price)
        except (ValueError, TypeError):
            return ValidationResult(passed=False, warnings=["Price is not a valid number"])
            
    if price <= 0:
        return ValidationResult(passed=False, warnings=["Price is zero or negative"])

    # Check if price matches phone fragment
    price_str = str(int(price))
    if phone:
        phone_clean = _clean_phone_for_comparison(phone)
        if len(price_str) >= 5 and price_str in phone_clean:
            return ValidationResult(passed=False, warnings=[f"Price {price} is a fragment of phone number {phone}"])

    # Range checks based on listing type
    ltype = listing_type.lower() if listing_type else "rent"
    
    if ltype == "rent" or ltype == "lease":
        if price > MAX_RENT_PRICE:
            return ValidationResult(passed=False, warnings=[f"Price {price} is impossibly high for rent"])
        if price < MIN_RENT_PRICE:
            return ValidationResult(passed=False, warnings=[f"Price {price} is impossibly low for rent"])
            
    if ltype == "sale":
        if price < MIN_SALE_PRICE:
            return ValidationResult(passed=False, warnings=[f"Price {price} is impossibly low for sale"])
        if price > MAX_SALE_PRICE:
            return ValidationResult(passed=False, warnings=[f"Price {price} is impossibly high for sale"])

    return ValidationResult(passed=True, updated_value=price)

def validate_locality(locality: str, group_name: str) -> ValidationResult:
    if not locality:
        return ValidationResult(passed=False, warnings=["Locality is empty"])
        
    loc_clean = locality.strip().lower()
    
    if loc_clean == "unknown":
        return ValidationResult(passed=False, warnings=["Locality is explicitly unknown"])

    # Check against known metadata headers
    for header in KNOWN_METADATA_HEADERS:
        if header in loc_clean:
            return ValidationResult(passed=False, warnings=["Locality contains forwarded metadata headers"])
            
    # Check against exact group name
    if group_name:
        group_clean = group_name.strip().lower()
        if loc_clean == group_clean:
            return ValidationResult(passed=False, warnings=["Locality perfectly matches group name"])
            
        # Check against known group patterns
        for pattern in KNOWN_GROUP_PATTERNS:
            if re.match(pattern, loc_clean, re.IGNORECASE):
                return ValidationResult(passed=False, warnings=["Locality matches known WhatsApp group pattern"])

    return ValidationResult(passed=True, updated_value=locality.strip())

def validate_listing(doc: Dict[str, Any]) -> ValidationResult:
    warnings = []
    penalties = []
    
    ptype = str(doc.get("property_type", "")).lower()
    ltype = str(doc.get("listing_type", "")).lower()
    bhk = doc.get("bhk", 0)
    
    if ptype in ("apartment", "flat", "villa", "house", "builder_floor"):
        if bhk == 0:
            warnings.append("Residential property with BHK=0")
            # This is fatal, shouldn't happen. Can't be repaired cleanly usually, but we will let repair orchestrator decide
            penalties.append("bhk_zero_residential")
            
    if ptype in ("commercial", "office", "shop", "showroom", "land", "agricultural"):
        if bhk > 0:
            warnings.append(f"{ptype} listing cannot have BHK")
            penalties.append("bhk_on_commercial")
            
    # Return passed=False if we want to explicitly reject impossible combos in the orchestrator
    if warnings:
        return ValidationResult(passed=False, warnings=warnings, penalties=penalties)
        
    return ValidationResult(passed=True)

def validate_required_fields(doc: Dict[str, Any]) -> ValidationResult:
    warnings = []
    
    # Must have property type
    if not doc.get("property_type"):
        warnings.append("Missing property_type")
        
    # Must have listing type
    if not doc.get("listing_type"):
        warnings.append("Missing listing_type")
        
    # Must have a contact mechanism (broker_phone or source.broker_phone)
    phone = doc.get("broker_phone")
    if not phone and "source" in doc and doc["source"].get("broker_phone"):
        phone = doc["source"]["broker_phone"]
    if not phone:
        warnings.append("Missing broker_phone contact")
        
    # Must have some location signal
    loc = doc.get("area") or doc.get("locality") or doc.get("city")
    if not loc or loc.lower() == "unknown":
        warnings.append("Missing any valid location signals")
        
    # Must have at least one pricing signal (price, deposit, etc)
    price = doc.get("price", 0)
    if price <= 0:
        warnings.append("Missing valid price")
        
    if len(warnings) >= 3:
        # If it misses 3 or more crucial things, it's garbage
        return ValidationResult(passed=False, warnings=warnings, penalties=["too_many_missing_fields"])
        
    if warnings:
        return ValidationResult(passed=True, warnings=warnings) # Passed but with warnings
        
    return ValidationResult(passed=True)


def repair_property(doc: Dict[str, Any], raw_text: str, source_group: str) -> Tuple[bool, Dict[str, Any]]:
    """
    Orchestrates the semantic validation and deterministic repair.
    Mutates doc in-place safely.
    Returns (is_valid, doc). If is_valid is False, it should go to review queue.
    """
    val_errors = []
    warnings = doc.get("warnings", [])
    if not isinstance(warnings, list):
        warnings = []
    missing_fields = doc.get("missing_fields", [])
    if not isinstance(missing_fields, list):
        missing_fields = []
        
    score_penalty = 0
    
    # 1. Requirement Post Check (Absolute Fatal)
    intent = CategoryAExtractor.detect_intent(raw_text)
    if intent["is_requirement"]:
        val_errors.append("Requirement post cannot become a property listing")
        doc["validation_errors"] = val_errors
        return False, doc
        
    raw_lower = raw_text.lower()
    for req_word in KNOWN_REQUIREMENT_KEYWORDS:
        if req_word in raw_lower:
            # We must be careful not to trigger on "no requirement" or something, but standard is strict
            # For now, rely heavily on deterministic parser intent, but add extra strict check for simple single words
            pass

    phone = str(doc.get("broker_phone", ""))
    if not phone and "source" in doc and doc["source"].get("broker_phone"):
        phone = str(doc["source"]["broker_phone"])
        
    # 2. Validate & Repair Title
    title_res = validate_title(doc.get("title", ""), phone, intent)
    if not title_res.passed:
        # Repair strategy: Generate from fields
        bhk = doc.get("bhk", 0)
        ptype = str(doc.get("property_type", "Property")).title()
        area = str(doc.get("area", "")).strip()
        
        new_title = ""
        if bhk > 0 and ptype:
            new_title = f"{bhk} BHK {ptype}"
        elif ptype:
            new_title = ptype
        else:
            new_title = "Property Listing"
            
        if area and area.lower() != "unknown":
            new_title += f" in {area.title()}"
            
        doc["title"] = new_title
        score_penalty += 10
        warnings.append("Title was repaired deterministically")
        
    # 3. Validate & Repair Price
    price = doc.get("price", 0)
    listing_type = doc.get("listing_type", "rent")
    if price > 0:
        price_res = validate_price(price, phone, listing_type)
        if not price_res.passed:
            # Repair strategy: Null out the price
            doc["price"] = 0
            if "normalized_price_inr" in doc:
                doc["normalized_price_inr"] = 0
            score_penalty += 15
            warnings.extend(price_res.warnings)
            missing_fields.append("price")
            
    # 4. Validate & Repair Locality/Area
    area = doc.get("area", "")
    area_res = validate_locality(area, source_group)
    if not area_res.passed:
        # Repair strategy: Fallback to Unknown
        doc["area"] = "Unknown"
        doc["locality"] = "Unknown"
        doc["canonical_locality"] = None
        doc["locality_id"] = None
        score_penalty += 10
        warnings.extend(area_res.warnings)
        if "area" not in missing_fields:
            missing_fields.append("area")

    # 5. Validate Listing Logic
    listing_res = validate_listing(doc)
    if not listing_res.passed:
        if "bhk_on_commercial" in listing_res.penalties:
            # Repair strategy: Null out BHK
            doc["bhk"] = 0
            score_penalty += 5
            warnings.append("BHK removed from commercial listing")
        elif "bhk_zero_residential" in listing_res.penalties:
            # Fatal if we can't repair. But maybe it's just a plot/land misclassified?
            # We don't guess. Send to review.
            val_errors.extend(listing_res.warnings)

    # 6. Validate Required Fields (End of line check)
    req_res = validate_required_fields(doc)
    if not req_res.passed:
        val_errors.extend(req_res.warnings)
        val_errors.append("Property lacks minimum viable data")
        
    # Update Document Metadata
    doc["warnings"] = list(set(warnings))
    doc["missing_fields"] = list(set(missing_fields))
    
    current_score = doc.get("listing_quality_score", 100)
    doc["listing_quality_score"] = max(0, current_score - score_penalty)
    
    if val_errors:
        doc["validation_errors"] = val_errors
        return False, doc
        
    return True, doc
