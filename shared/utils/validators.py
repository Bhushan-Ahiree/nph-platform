import re
from typing import Dict, Any, Tuple, List
from shared.utils.semantic_validation import repair_property

class PropertyValidator:
    """
    Deterministic pre-insertion validation layer.
    Enforces absolute ground-truth business rules to prevent LLM hallucinations
    and corrupted data from entering active inventory collections.
    """
    @staticmethod
    def validate_property(doc: Dict[str, Any], raw_text: str, source_group: str) -> Tuple[bool, List[str]]:
        errors = []
        # Ensure raw text is preserved on the document for audit traceability
        if not raw_text or not raw_text.strip():
            return False, ["Empty raw text provided"]
            
        doc["raw_text"] = raw_text

        # --- Legacy Guardrails ---
        from shared.utils.deterministic_parser import CategoryAExtractor
        intent = CategoryAExtractor.detect_intent(raw_text)
        
        # Rule 1: Requirement posts must NEVER become properties
        if intent["is_requirement"]:
            errors.append("Requirement post cannot become a property listing")

        # Rule 2: "40 lakh" can NEVER become 4 crore / Price must match original text
        extracted_price_info = CategoryAExtractor.extract_price(raw_text)
        det_price = extracted_price_info["price"]
        doc_price = doc.get("price", 0)

        # Explicit check for 40 lakh -> 4 crore hallucination
        s_text = raw_text.lower()
        if any(term in s_text for term in ("40 lakh", "40 लाख", "40 lacs")) and doc_price == 40000000:
            errors.append("Price magnitude mismatch: '40 lakh' cannot become 4 crore")
        elif det_price > 0 and doc_price > 0 and det_price != doc_price:
            # If deterministic price is solid, doc price must not wildly diverge in magnitude
            if (doc_price == det_price * 10) or (doc_price == det_price * 100) or (doc_price == det_price / 10):
                errors.append(f"Price magnitude mismatch: extracted {doc_price} vs deterministic {det_price}")

        # Rule 3: Rent listings cannot contain crore-level prices unless explicitly supported
        listing_type = doc.get("listing_type", "rent")
        if listing_type == "rent" and doc_price >= 10000000:
            errors.append("Rent listing cannot contain crore-level price")

        # Rule 4: Agricultural listings cannot become apartments
        doc_prop_type = doc.get("property_type", "apartment")
        if intent["property_type"] == "land" and doc_prop_type in ("apartment", "flat", "commercial"):
            errors.append("Agricultural/land listing cannot become an apartment")
            
        # Rule 7: listing_type must match detected intent
        if intent["listing_type"] != listing_type:
            if intent["listing_type"] in ("sale", "lease", "rent") and listing_type in ("rent", "sale"):
                if (intent["listing_type"] == "sale" and listing_type == "rent") or (intent["listing_type"] == "rent" and listing_type == "sale"):
                    errors.append(f"Listing type mismatch: detected {intent['listing_type']} vs model {listing_type}")

        # --- New Semantic Orchestrator ---
        is_valid, updated_doc = repair_property(doc, raw_text, source_group)
        
        # Copy mutated fields back to doc in case caller relies on reference mutability 
        for k, v in updated_doc.items():
            doc[k] = v
            
        val_errors = doc.get("validation_errors", [])
        
        # Combine all errors
        all_errors = errors + val_errors
        
        if all_errors:
            doc["validation_errors"] = all_errors
            return False, all_errors
            
        return is_valid, []
