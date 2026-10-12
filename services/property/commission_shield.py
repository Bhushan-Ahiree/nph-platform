# services/property/commission_shield.py
from typing import Dict, Any

def shield_property(property_data: Dict[str, Any], role: str = "PUBLIC") -> Dict[str, Any]:
    """
    Applies role-based data isolation on property documents.
    - PUBLIC: Standard customers. Blinds address strings, tower details, and phones.
    - INTERNAL: Field operations (Mom). Exposes complete logistical tracking variables.
    - ADMIN: Full visibility plus analytical tracking infrastructure.
    """
    if hasattr(property_data, "model_dump"):
        sanitized = property_data.model_dump()
    elif hasattr(property_data, "dict"):
        sanitized = property_data.dict()
    else:
        sanitized = property_data.copy()
    
    # Enforce stringification of MongoDB ObjectIds
    if "_id" in sanitized:
        sanitized["_id"] = str(sanitized["_id"])
        sanitized["id"] = sanitized["_id"]
        if "property_id" not in sanitized:
            sanitized["property_id"] = sanitized["_id"]

    # Construct analytical match justifications if not populated by search loops
    if "match_reason" not in sanitized:
        reasons = ["Structural Parameter Match"]
        if sanitized.get("confidence_score", 100) >= 90:
            reasons.append("High Confidence Listing")
        if sanitized.get("availability_status") == "VERIFIED":
            reasons.append("Freshly Verified Asset")
        sanitized["match_reason"] = reasons

    if role == "PUBLIC":
        sanitized["building_name"] = "Hidden until site visit confirmation"
        sanitized["exact_address"] = "Hidden until site visit confirmation"
        sanitized["broker_phone"] = "Hidden until site visit confirmation"
        sanitized["owner_phone"] = "Hidden until site visit confirmation"
        sanitized["google_pin"] = "Hidden until site visit confirmation"
        
        # Culled elements to avoid exposure via dynamic dictionaries
        sanitized.pop("raw_message_id", None)
        sanitized.pop("ingestion_hash", None)
        sanitized.pop("status", None)
    
    elif role == "INTERNAL":
        # Internal operations requires visibility, but suppresses system logs
        sanitized.pop("ingestion_hash", None)
        
    return sanitized
