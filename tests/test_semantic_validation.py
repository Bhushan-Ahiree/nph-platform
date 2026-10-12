from shared.utils.semantic_validation import (
    validate_title,
    validate_price,
    validate_locality,
    validate_listing,
    repair_property
)

def test_validate_title_empty():
    res = validate_title("", "1234567890", {})
    assert not res.passed
    assert "Title is empty" in res.warnings[0]

def test_validate_title_generic():
    res = validate_title("Property Listing", "1234567890", {})
    assert not res.passed
    assert "placeholder" in res.warnings[0]

def test_validate_title_phone():
    res = validate_title("9000000008", "9000000008", {})
    assert not res.passed
    assert "phone number" in res.warnings[0]
    
    res2 = validate_title("Contact: 9000000008", "9000000008", {})
    assert not res2.passed
    assert "phone number" in res2.warnings[0] or "contact number" in res2.warnings[0]

def test_validate_price_phone_fragment():
    # Example: phone is 9345678012, price extracted is 93456
    res = validate_price(93456, "9345678012", "rent")
    assert not res.passed
    assert "fragment" in res.warnings[0]
    
def test_validate_price_limits():
    # Rent limits
    assert validate_price(10000, "1234567890", "rent").passed
    assert not validate_price(400, "1234567890", "rent").passed # Below MIN_RENT_PRICE
    assert not validate_price(10000000, "1234567890", "rent").passed # Above MAX_RENT_PRICE
    
    # Sale limits
    assert validate_price(5000000, "1234567890", "sale").passed
    assert not validate_price(5000, "1234567890", "sale").passed # Below MIN_SALE_PRICE
    assert not validate_price(600000000, "1234567890", "sale").passed # Above MAX_SALE_PRICE

def test_validate_locality_group_name():
    # Exact match
    res = validate_locality("कान्हादेश/कसमादे ( नाशिक) 👑🚩1", "कान्हादेश/कसमादे ( नाशिक) 👑🚩1")
    assert not res.passed
    
    # Regex pattern match
    res2 = validate_locality("कान्हादेश/कसमादे ( नाशिक)", "Some other group")
    assert not res2.passed
    assert "WhatsApp group pattern" in res2.warnings[0]

def test_validate_listing_impossible_combos():
    doc1 = {"property_type": "apartment", "bhk": 0}
    res1 = validate_listing(doc1)
    assert not res1.passed
    assert "bhk_zero_residential" in res1.penalties
    
    doc2 = {"property_type": "commercial", "bhk": 2}
    res2 = validate_listing(doc2)
    assert not res2.passed
    assert "bhk_on_commercial" in res2.penalties

def test_repair_property_requirement_post():
    raw_text = "I am looking for a 2 bhk on rent in indira nagar. Please contact if you have. पाहिजे."
    doc = {
        "title": "2 BHK in Indira Nagar",
        "price": 15000,
        "property_type": "apartment",
        "listing_type": "rent",
        "area": "Indira Nagar",
        "broker_phone": "9999999999"
    }
    is_valid, updated_doc = repair_property(doc, raw_text, "Some Group")
    assert not is_valid
    assert "Requirement post cannot become a property listing" in updated_doc["validation_errors"]

def test_repair_property_phone_title():
    raw_text = "2 bhk flat for rent. 9000000008"
    doc = {
        "title": "Contact: 9000000008",
        "price": 15000,
        "property_type": "apartment",
        "listing_type": "rent",
        "bhk": 2,
        "area": "Indira Nagar",
        "broker_phone": "9000000008"
    }
    is_valid, updated_doc = repair_property(doc, raw_text, "Some Group")
    assert is_valid
    # The title should be deterministically regenerated
    assert updated_doc["title"] == "2 BHK Apartment in Indira Nagar"
    assert "Title was repaired deterministically" in updated_doc["warnings"]

def test_repair_property_group_name_locality():
    raw_text = "2 bhk flat for rent 15k."
    doc = {
        "title": "2 BHK Apartment",
        "price": 15000,
        "property_type": "apartment",
        "listing_type": "rent",
        "bhk": 2,
        "area": "कान्हादेश/कसमादे ( नाशिक)",
        "broker_phone": "9999999999"
    }
    is_valid, updated_doc = repair_property(doc, raw_text, "कान्हादेश/कसमादे ( नाशिक)")
    assert is_valid
    assert updated_doc["area"] == "Unknown"
    assert updated_doc["locality"] == "Unknown"
    assert "Locality perfectly matches group name" in updated_doc["warnings"] or "Locality matches known WhatsApp group pattern" in updated_doc["warnings"]

def test_repair_property_phone_fragment_price():
    raw_text = "commercial property. contact 9345678012"
    doc = {
        "title": "Commercial Property",
        "price": 93456,
        "property_type": "commercial",
        "listing_type": "rent",
        "bhk": 0,
        "area": "Indira Nagar",
        "broker_phone": "9345678012"
    }
    is_valid, updated_doc = repair_property(doc, raw_text, "Some Group")
    assert is_valid
    assert updated_doc["price"] == 0
    assert "price" in updated_doc["missing_fields"]

def test_repair_property_empty_record():
    doc = {
        "title": "Property Listing",
        "price": 0,
        "property_type": "apartment",
        "listing_type": "rent",
        "bhk": 0,
        "area": "Unknown",
        "broker_phone": ""
    }
    is_valid, updated_doc = repair_property(doc, "some text", "Some Group")
    assert not is_valid
    assert "Property lacks minimum viable data" in updated_doc["validation_errors"]
