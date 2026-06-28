import os
import pytest
from unittest.mock import patch, MagicMock
from apps.worker.tasks.ingestion_tasks import (
    preprocess_whatsapp_text,
    is_real_estate_listing,
    process_raw_group_dump
)
from shared.utils.normalization import (
    normalise_extracted_property,
    compute_ingestion_hash,
    resolve_canonical_locality
)
from apps.api.schemas.property_schema_v2 import PropertySchemaV2

def test_resolve_canonical_locality_aliases():
    """Verify canonical locality alias mapping without overwriting raw data."""
    assert resolve_canonical_locality("Gangapur") == "Gangapur Road"
    assert resolve_canonical_locality("Gangapur Road") == "Gangapur Road"
    assert resolve_canonical_locality("Gangapur Rd") == "Gangapur Road"
    assert resolve_canonical_locality("GangapurRoad") == "Gangapur Road"
    
    assert resolve_canonical_locality("Pathardi") == "Pathardi"
    assert resolve_canonical_locality("Pathardi Phata") == "Pathardi"
    assert resolve_canonical_locality("Pathardi Gaon") == "Pathardi"
    
    assert resolve_canonical_locality("College Rd") == "College Road"
    assert resolve_canonical_locality("Indira Nagar") == "Indira Nagar"
    assert resolve_canonical_locality("Mumbai Naka") == "Mumbai Naka"
    assert resolve_canonical_locality("CBS Circle") == "CBS"
    assert resolve_canonical_locality("BYK") == "BYK College"
    assert resolve_canonical_locality("Vidya Vikas Circle") == "Vidya Vikas Circle"


def test_marathi_whatsapp_dump_extraction():
    """Verify extraction quality for Marathi WhatsApp listings."""
    raw = {
        "title": "नाशिक रोड ला २ BHK फ्लॅट विकणे आहे",
        "description": "उत्कृष्ट फ्लॅट, लिफ्ट आणि पार्किंग उपलब्ध",
        "property_type": "apartment",
        "listing_type": "sale",
        "city": "Nashik",
        "raw_locality": "Nashik Road",
        "bhk": 2,
        "price": "35 लाख",
        "carpet_area_sqft": "900 sqft",
        "broker_phone": "9000000001",
        "ownership_type": "broker",
        "possession_status": "Ready Possession",
        "furnishing_status": "Semi Furnished",
        "amenities": ["Lift", "Parking"],
        "landmarks": ["Nashik Road Station"]
    }
    hash_val = compute_ingestion_hash("3500000", "Nashik Road", 2, "sale", "9000000001")
    norm = normalise_extracted_property(raw, "Nashik Agents", hash_val)
    
    assert norm["price"] == 3500000
    assert norm["carpet_area_sqft"] == 900
    assert norm["raw_locality"] == "Nashik Road"
    assert norm["canonical_locality"] == "Nashik Road"
    assert norm["possession_status"] == "Ready Possession"
    assert norm["furnishing_status"] == "Semi Furnished"
    assert "Lift" in norm["amenities"]
    assert norm["listing_quality_score"] == 100
    assert len(norm["missing_fields"]) == 0


def test_english_whatsapp_dump_extraction():
    """Verify extraction quality for English WhatsApp listings."""
    raw = {
        "title": "Premium 3 BHK Flat in College Road",
        "description": "Spacious flat with Terrace and Garden view",
        "property_type": "apartment",
        "listing_type": "sale",
        "city": "Nashik",
        "raw_locality": "College Rd",
        "bhk": 3,
        "price": "1.2 Crore",
        "carpet_area_sqft": "1800 sqft",
        "broker_phone": "9876543210",
        "poster_type": "Owner",
        "possession_status": "Under Construction",
        "furnishing_status": "Unfurnished",
        "amenities": ["Terrace", "Garden"],
        "landmarks": ["BYK College"]
    }
    hash_val = compute_ingestion_hash("12000000", "College Rd", 3, "sale", "9876543210")
    norm = normalise_extracted_property(raw, "Nashik Premium Homes", hash_val)
    
    assert norm["price"] == 12000000
    assert norm["carpet_area_sqft"] == 1800
    assert norm["raw_locality"] == "College Rd"
    assert norm["canonical_locality"] == "College Road"
    assert norm["possession_status"] == "Under Construction"
    assert norm["furnishing_status"] == "Unfurnished"
    assert norm["poster_type"] == "Owner"
    assert "BYK College" in norm["landmarks"]
    assert norm["listing_quality_score"] == 100


def test_mixed_language_and_emoji_heavy_extraction():
    """Verify extraction quality for mixed language and emoji heavy WhatsApp listings."""
    raw_text = "🚨 🔥 Urgent Sale! 🔥 🚨 👉 Govind Nagar मध्ये 1 BHK लक्झरीयस फ्लॅट 🏡 💰 Price: ₹25 Lakhs only! 📞 Call 9822001122 🏃‍♂️💨"
    assert is_real_estate_listing(raw_text)
    
    raw = {
        "title": "1 BHK Luxurious Flat in Govind Nagar",
        "description": "Urgent Sale!",
        "property_type": "apartment",
        "listing_type": "sale",
        "city": "Nashik",
        "raw_locality": "Govind Nagar",
        "bhk": 1,
        "price": "25 Lakhs",
        "broker_phone": "9822001122",
        "poster_type": "Broker",
        "possession_status": "Immediate Possession",
        "furnishing_status": "Fully Furnished",
        "amenities": ["Power Backup", "Security"]
    }
    hash_val = compute_ingestion_hash("2500000", "Govind Nagar", 1, "sale", "9822001122")
    norm = normalise_extracted_property(raw, "Urgent Deals Group", hash_val)
    
    assert norm["price"] == 2500000
    assert norm["canonical_locality"] == "Govind Nagar"
    assert norm["possession_status"] == "Immediate Possession"
    assert norm["furnishing_status"] == "Fully Furnished"
    assert norm["poster_type"] == "Broker"
    assert norm["listing_quality_score"] == 85  # missing area deducts 15
    assert "area" in norm["missing_fields"]


def test_forwarded_messages_preprocessing():
    """Verify that Forwarded messages are correctly cleaned."""
    raw_text = "Forwarded\n[11:04 am, 27/06/2026] +91 90000 00001: 2 BHK flat in Gangapur Road for buy"
    cleaned = preprocess_whatsapp_text(raw_text)
    assert "Forwarded" not in cleaned
    assert "[11:04 am, 27/06/2026]" not in cleaned
    assert "2 BHK flat in Gangapur Road for buy" in cleaned


def test_builder_ads_intelligence():
    """Verify extraction of builder and project names across known top builders."""
    builders = ["Ashoka", "Suyojit", "Hari", "Roongta", "Dream City", "Ekdant", "Shriram", "Datar"]
    
    for builder in builders:
        raw = {
            "title": f"{builder} Paradise 2 BHK Flat",
            "property_type": "apartment",
            "listing_type": "sale",
            "city": "Nashik",
            "raw_locality": "Pathardi Phata",
            "bhk": 2,
            "price": "45 लाख",
            "carpet_area_sqft": "1050 sqft",
            "broker_phone": "9822334455",
            "builder_name": builder,
            "project_name": f"{builder} Paradise",
            "poster_type": "Builder",
            "possession_status": "New Booking",
            "furnishing_status": "Unfurnished"
        }
        hash_val = compute_ingestion_hash("4500000", "Pathardi Phata", 2, "sale", "9822334455")
        norm = normalise_extracted_property(raw, "Builder Network", hash_val)
        
        assert norm["builder_name"] == builder
        assert norm["project_name"] == f"{builder} Paradise"
        assert norm["poster_type"] == "Builder"
        assert norm["possession_status"] == "New Booking"
        assert norm["canonical_locality"] == "Pathardi"


def test_pg_and_roommate_extraction():
    """Verify extraction quality for PG and Roommate listings."""
    raw_pg = {
        "title": "Boys PG in Mahatma Nagar",
        "property_type": "pg",
        "listing_type": "pg",
        "city": "Nashik",
        "raw_locality": "Mahatma Nagar",
        "price": "4500 monthly",
        "broker_phone": "9988776655",
        "poster_type": "Owner",
        "amenities": ["Furnished", "Swimming Pool", "Gym"]
    }
    hash_val = compute_ingestion_hash("4500", "Mahatma Nagar", 0, "pg", "9988776655")
    norm_pg = normalise_extracted_property(raw_pg, "PG Group", hash_val)
    
    assert norm_pg["price"] == 4500
    assert norm_pg["property_type"] == "pg"
    assert norm_pg["listing_type"] == "pg"
    assert norm_pg["canonical_locality"] == "Mahatma Nagar"
    assert norm_pg["poster_type"] == "Owner"
    assert "Gym" in norm_pg["amenities"]


def test_commercial_and_agricultural_and_jv_extraction():
    """Verify extraction quality for Commercial shops, Agricultural land, and Joint Ventures."""
    raw_comm = {
        "title": "Commercial Shop in Dwarka Circle",
        "property_type": "commercial",
        "listing_type": "rent",
        "city": "Nashik",
        "raw_locality": "Dwarka Circle",
        "price": "25000",
        "carpet_area_sqft": "400 sqft",
        "broker_phone": "9123456780",
        "poster_type": "Channel Partner"
    }
    norm_comm = normalise_extracted_property(raw_comm, "Comm Group", "hash1")
    assert norm_comm["property_type"] == "commercial"
    assert norm_comm["canonical_locality"] == "Dwarka"
    assert norm_comm["poster_type"] == "Channel Partner"
    
    raw_agri = {
        "title": "5 Acre Agricultural Land in Trimbak",
        "property_type": "agricultural",
        "listing_type": "sale",
        "city": "Nashik",
        "raw_locality": "Trimbak",
        "price": "50 Lakhs",
        "carpet_area_sqft": "5 Acre",
        "broker_phone": "9123456780",
        "poster_type": "Investor"
    }
    norm_agri = normalise_extracted_property(raw_agri, "Agri Group", "hash2")
    assert norm_agri["property_type"] == "agricultural"
    assert norm_agri["carpet_area_sqft"] == 5 * 43560
    assert norm_agri["poster_type"] == "Investor"
    
    raw_jv = {
        "title": "Prime Joint Venture Proposal in Mumbai Naka",
        "property_type": "jv",
        "listing_type": "jv",
        "city": "Nashik",
        "raw_locality": "Mumbai Naka",
        "price": "5 Crore",
        "broker_phone": "9123456780",
        "poster_type": "Developer"
    }
    norm_jv = normalise_extracted_property(raw_jv, "JV Group", "hash3")
    assert norm_jv["property_type"] == "jv"
    assert norm_jv["canonical_locality"] == "Mumbai Naka"
    assert norm_jv["poster_type"] == "Developer"


def test_luxury_rental_and_sale_extraction():
    """Verify extraction quality for Luxury, Rental, and Sale properties."""
    raw_lux = {
        "title": "Super Luxury 5 BHK Villa in Gangapur Road",
        "property_type": "villa",
        "listing_type": "sale",
        "city": "Nashik",
        "raw_locality": "GangapurRoad",
        "bhk": 5,
        "price": "7.5 Crore",
        "carpet_area_sqft": "6000 sqft",
        "broker_phone": "9898989898",
        "poster_type": "Builder",
        "amenities": ["Club House", "Swimming Pool", "Garden", "Power Backup"],
        "landmarks": ["Vidya Vikas Circle"]
    }
    norm_lux = normalise_extracted_property(raw_lux, "Luxury Group", "hash_lux")
    assert norm_lux["price"] == 75000000
    assert norm_lux["canonical_locality"] == "Gangapur Road"
    assert "Club House" in norm_lux["amenities"]
    assert "Vidya Vikas Circle" in norm_lux["landmarks"]
    assert norm_lux["listing_quality_score"] == 100


def test_deterministic_scoring_and_diagnostics():
    """Verify deterministic listing quality score and diagnostics for defective listings."""
    raw_defective = {
        "title": "Flat for sale",
        "property_type": "apartment",
        "listing_type": "sale",
        "city": "Nashik",
        "price": 0,
        "broker_phone": None,
        "carpet_area_sqft": None,
        "raw_locality": "Unknown",
        "warnings": ["spam probability"]
    }
    norm_def = normalise_extracted_property(raw_defective, "Spam Group", "hash_def")
    
    assert "price" in norm_def["missing_fields"]
    assert "phone" in norm_def["missing_fields"]
    assert "area" in norm_def["missing_fields"]
    assert "location" in norm_def["missing_fields"]
    assert norm_def["listing_quality_score"] == 0  # 100 - 25(price) - 20(phone) - 15(area) - 20(location) - 30(spam) = 0
    assert norm_def["confidence_breakdown"]["price"] == 0
    assert norm_def["confidence_breakdown"]["phone"] == 0
    assert norm_def["confidence_breakdown"]["locality"] == 0


@patch("apps.worker.tasks.ingestion_tasks.get_db")
@patch("apps.worker.tasks.ingestion_tasks.call_ollama_extract")
def test_full_process_raw_group_dump_sprint_g(mock_call_ollama, mock_get_db):
    """Verify end-to-end processing of a raw group dump incorporating all Sprint G intelligence."""
    mock_db = MagicMock()
    mock_get_db.return_value = mock_db
    
    mock_properties_col = MagicMock()
    mock_properties_col.find_one.return_value = None
    
    cols_dict = {
        "properties": mock_properties_col,
        "pg_listings": MagicMock(),
        "webhook_events": MagicMock(),
        "broker_profiles": MagicMock(),
        "raw_message_logs": MagicMock(),
        "agricultural_jv_listings": MagicMock(),
        "out_of_network_properties": MagicMock(),
        "leads": MagicMock(),
        "recommendation_history": MagicMock(),
    }
    mock_db.__getitem__.side_effect = lambda key: cols_dict.setdefault(key, MagicMock())

    mock_call_ollama.return_value = [
        {
            "title": "Suyojit Viridian 3 BHK in Gangapur Road",
            "description": "Ready possession flat with lift and club house",
            "property_type": "apartment",
            "listing_type": "sale",
            "city": "Nashik",
            "raw_locality": "Gangapur Road",
            "bhk": 3,
            "price": "85 लाख",
            "carpet_area_sqft": "1500 sqft",
            "broker_phone": "9000000001",
            "builder_name": "Suyojit",
            "project_name": "Suyojit Viridian",
            "poster_type": "Builder",
            "possession_status": "Ready Possession",
            "furnishing_status": "Semi Furnished",
            "amenities": ["Lift", "Club House"],
            "landmarks": ["Vidya Vikas Circle"]
        }
    ]

    summary = process_raw_group_dump.apply(args=("Suyojit Official Group", "Suyojit Viridian 3 BHK in Gangapur Road. Ready possession flat with lift and club house. 85 लाख. Call 9000000001", "evt_sprint_g_1")).get()

    assert summary["status"] == "completed"
    assert summary["inserted"] == 1
    mock_properties_col.insert_one.assert_called_once()
