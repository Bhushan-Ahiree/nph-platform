import os
import pytest
from unittest.mock import patch
from shared.utils.deterministic_parser import WhatsAppTokenizer, CategoryAExtractor, CategoryBExtractor
from shared.utils.validators import PropertyValidator
from apps.worker.tasks.ingestion_tasks import preprocess_whatsapp_text, split_into_message_blocks, is_real_estate_listing, process_raw_group_dump

@pytest.fixture
def raw_dump_text():
    dump_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "samples", "sample_whatsapp_dump.txt")
    with open(dump_path, "r", encoding="utf-8") as f:
        return f.read()

def test_deterministic_extraction_on_sample_dump(raw_dump_text):
    cleaned = preprocess_whatsapp_text(raw_dump_text)
    strategy, blocks = split_into_message_blocks(cleaned)
    assert len(blocks) > 0

    # Test Block 1: 3 BHK Row house rent 13000
    b1 = WhatsAppTokenizer.clean_text(blocks[0])
    b1_intent = CategoryAExtractor.detect_intent(b1)
    b1_price = CategoryAExtractor.extract_price(b1)
    b1_bhk = CategoryAExtractor.extract_bhk(b1)
    b1_phone = CategoryAExtractor.extract_phone(b1)
    
    assert b1_intent["is_requirement"] is False
    assert b1_intent["listing_type"] == "rent"
    assert b1_bhk["bhk"] == 3
    assert b1_price["price"] == 13000
    assert b1_phone == "9000000010"

    # Test Block 4: 40 Lakh 2 BHK Flat
    b4_found = False
    for block in blocks:
        if "40 लाख" in block or "40 lakh" in block:
            b4 = WhatsAppTokenizer.clean_text(block)
            b4_intent = CategoryAExtractor.detect_intent(b4)
            b4_price = CategoryAExtractor.extract_price(b4)
            b4_bhk = CategoryAExtractor.extract_bhk(b4)
            b4_area = CategoryAExtractor.extract_area(b4)
            b4_phone = CategoryAExtractor.extract_phone(b4)
            
            assert b4_intent["is_requirement"] is False
            assert b4_intent["listing_type"] == "sale"
            assert b4_price["price"] == 4000000
            assert b4_bhk["bhk"] == 2
            assert b4_area["carpet_area_sqft"] == 1000
            assert b4_phone == "9000000001"
            b4_found = True
            break
    assert b4_found

    # Test Requirement Post: 400 to 500 vaar plot wanted
    req_found = False
    for block in blocks:
        if "रिक्वायरमेंट" in block:
            breq = WhatsAppTokenizer.clean_text(block)
            breq_intent = CategoryAExtractor.detect_intent(breq)
            assert breq_intent["is_requirement"] is True
            req_found = True
            break
    assert req_found

    # Test crore-level prices: 12.50 Cr and 1.21 Cr and 1.21 Cr
    cr1_found = False
    cr2_found = False
    for block in blocks:
        if "12.50 Cr" in block:
            bcr1 = WhatsAppTokenizer.clean_text(block)
            p1 = CategoryAExtractor.extract_price(bcr1)
            assert p1["price"] == 125000000
            cr1_found = True
        if "1.21 Cr" in block:
            bcr2 = WhatsAppTokenizer.clean_text(block)
            p2 = CategoryAExtractor.extract_price(bcr2)
            assert p2["price"] == 12100000
            cr2_found = True
    assert cr1_found
    assert cr2_found

    # Test Spam Filtering: The Sneh Events
    spam_found = False
    for block in blocks:
        if "Sneh Events" in block or "फॅशन शो" in block:
            assert is_real_estate_listing(block) is False
            spam_found = True
    assert spam_found

def test_property_validator_guardrails():
    # Test 40 lakh -> 4 crore hallucination rejection
    doc1 = {"title": "2 BHK Flat", "price": 40000000, "listing_type": "sale", "property_type": "apartment", "bhk": 2}
    raw1 = "👉 नवीन 2 BHK फ्लॅट विकणे आहे 40 लाख सर्व खर्चा सोबत"
    is_valid, errors = PropertyValidator.validate_property(doc1, raw1, "Nashik Group")
    assert not is_valid
    assert "Price magnitude mismatch: '40 lakh' cannot become 4 crore" in errors

    # Test Requirement post rejection
    doc2 = {"title": "Plot Wanted", "price": 5000000, "listing_type": "sale", "property_type": "plot"}
    raw2 = "गंगापूर रोड ला प्लॉट अर्जंट विकत पाहिजे आहेत"
    is_valid, errors = PropertyValidator.validate_property(doc2, raw2, "Nashik Group")
    assert not is_valid
    assert "Requirement post cannot become a property listing" in errors

    # Test Rent crore-level price rejection
    doc3 = {"title": "Flat for rent", "price": 12500000, "listing_type": "rent", "property_type": "apartment", "bhk": 2}
    raw3 = "2 BHK flat for rent 12.50 Cr"
    is_valid, errors = PropertyValidator.validate_property(doc3, raw3, "Nashik Group")
    assert not is_valid
    assert "Rent listing cannot contain crore-level price" in errors

    # Test Group name area fallback rejection (now repaired deterministically)
    doc4 = {"title": "Flat for sale", "price": 3000000, "listing_type": "sale", "property_type": "apartment", "area": "SourceGroupA", "bhk": 2}
    raw4 = "2 BHK flat for sale 30 lakh"
    is_valid, errors = PropertyValidator.validate_property(doc4, raw4, "SourceGroupA")
    assert is_valid
    assert doc4["area"] == "Unknown"
    assert any("Locality perfectly matches group name" in w for w in doc4.get("validation_errors", []) + doc4.get("warnings", []))


@patch("apps.worker.tasks.ingestion_tasks.LLM_ENABLED", False)
@patch("apps.worker.tasks.ingestion_tasks.get_db")
@patch("apps.worker.tasks.ingestion_tasks.call_ollama_extract")
def test_sample_dump_ingests_without_llm(mock_call_ollama, mock_get_db, mock_db, raw_dump_text):
    """With LLM_ENABLED=false the deterministic parser output is ingested directly."""
    mock_get_db.return_value = mock_db.client.nph_core

    summary = process_raw_group_dump(
        source_group="Sample Nashik Property Group",
        raw_text=raw_dump_text,
        event_id="evt_sample_no_llm"
    )

    mock_call_ollama.assert_not_called()
    assert summary["status"] == "completed"
    assert summary["inserted"] == 6       # 8 messages minus 1 requirement post and 1 spam ad
    assert summary["failed"] == 1         # requirement post
    assert summary["spam_filtered"] == 1  # event promotion

    prices = sorted(d["price"] for d in mock_db.client.nph_core.properties._docs)
    assert prices == [9000, 13000, 3500000, 4000000, 12100000, 125000000]
