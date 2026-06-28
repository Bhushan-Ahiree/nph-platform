import pytest
from unittest.mock import MagicMock, patch
from apps.worker.tasks.ingestion_tasks import process_raw_group_dump, is_real_estate_listing, call_ollama_extract
from shared.utils.normalization import normalise_extracted_property

def test_is_real_estate_listing_spam_filtering():
    # Vehicle ads
    assert is_real_estate_listing("Maruti Swift for sale, model 2020, 15000 km driven") is False
    assert is_real_estate_listing("Activa for sale good condition") is False
    
    # Loans
    assert is_real_estate_listing("Get instant personal loan with no cibil check") is False
    
    # Events / greetings
    assert is_real_estate_listing("Good morning everyone, have a great day") is False
    assert is_real_estate_listing("Join my free masterclass webinar today") is False
    
    # Valid property listings
    assert is_real_estate_listing("2 BHK flat for rent in Indira Nagar 12k") is True
    assert is_real_estate_listing("Commercial plot available for lease in Pune") is True
    assert is_real_estate_listing("1 BHK apartment Mumbai 25000 rent") is True

def test_normalization_safe_price_and_safe_area():
    raw_prop = {
        "title": "2 BHK Indira Nagar",
        "price": "12.5 Lakhs",
        "carpet_area_sqft": "2 Guntha",
        "bhk": 2,
        "city": "Nashik",
        "listing_type": "sale",
        "broker_phone": "9876543210"
    }
    norm = normalise_extracted_property(raw_prop, "Test Group", "testhash")
    assert norm["price"] == 1250000  # 12.5 * 100000
    assert norm["carpet_area_sqft"] == 2178  # 2 * 1089

    raw_prop2 = {
        "title": "Villa Pune",
        "price": "1.5 Cr",
        "carpet_area_sqft": "100 Vaar",
        "bhk": 4,
        "city": "Pune",
        "listing_type": "sale",
        "broker_phone": "9876543210"
    }
    norm2 = normalise_extracted_property(raw_prop2, "Test Group", "testhash2")
    assert norm2["price"] == 15000000  # 1.5 * 10000000
    assert norm2["carpet_area_sqft"] == 900  # 100 * 9

@patch("apps.worker.tasks.ingestion_tasks.get_db")
@patch("apps.worker.tasks.ingestion_tasks.call_ollama_extract")
def test_process_raw_group_dump_filtering_and_routing(mock_ollama, mock_get_db):
    mock_db = MagicMock()
    mock_get_db.return_value = mock_db
    
    mock_properties_col = MagicMock()
    mock_properties_col.find_one.return_value = None
    mock_pg_col = MagicMock()
    mock_webhook_col = MagicMock()
    
    cols_dict = {
        "properties": mock_properties_col,
        "pg_listings": mock_pg_col,
        "webhook_events": mock_webhook_col,
        "broker_profiles": MagicMock(),
        "raw_message_logs": MagicMock(),
        "agricultural_jv_listings": MagicMock(),
        "out_of_network_properties": MagicMock(),
        "leads": MagicMock(),
        "recommendation_history": MagicMock(),
    }
    mock_db.__getitem__.side_effect = lambda key: cols_dict.setdefault(key, MagicMock())

    # Mock Ollama returning a mixed batch of valid, PG, Agri, and out-of-geo properties
    mock_ollama.return_value = [
        {
            "title": "2 BHK Indira Nagar",
            "property_type": "apartment",
            "listing_type": "rent",
            "city": "Nashik",
            "price": 12000,
            "broker_phone": "9876543210"
        },
        {
            "title": "Boys PG in College Road",
            "property_type": "pg",
            "listing_type": "rent",
            "city": "Nashik",
            "price": 5000,
            "broker_phone": "9876543211"
        },
        {
            "title": "5 Acre Agricultural Land for sale",
            "property_type": "land",
            "listing_type": "sale",
            "description": "Fertile agricultural sheti land",
            "city": "Nashik",
            "price": 5000000,
            "broker_phone": "9876543212"
        },
        {
            "title": "3 BHK Flat in Delhi",
            "property_type": "apartment",
            "listing_type": "rent",
            "city": "Delhi",
            "price": 30000,
            "broker_phone": "9876543213"
        }
    ]

    # Execute task
    summary = process_raw_group_dump.apply(args=("Test Group", "Sample raw text dump", "evt_123")).get()
    
    assert summary["status"] == "completed"
    assert summary["total_extracted"] == 4
    assert summary["inserted"] == 1  # Only the valid Nashik apartment goes to properties collection
    assert summary["pg_routed"] == 1  # PG routed to pg_listings
    assert summary["agri_discarded"] == 1  # Agri land discarded
    assert summary["out_of_geo"] == 1  # Delhi flat discarded

    mock_properties_col.insert_one.assert_called_once()
    mock_pg_col.insert_one.assert_called_once()
    mock_webhook_col.update_one.assert_called()
