# tests/test_ingestion_unification.py
import os
import sys
import pytest
import logging
from unittest.mock import patch, MagicMock

# Ensure scripts directory is in sys.path
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import ingest_dump

@pytest.fixture(autouse=True)
def clean_mock_db(mock_db):
    """Resets mock database collections before each test run."""
    mock_db.client.nph_core.properties._docs = []
    mock_db.client.nph_core.webhook_events._docs = []
    mock_db.client.nph_core.broker_profiles._docs = []
    yield

@patch("apps.api.routers.inventory.extract_property_details")
def test_inventory_ingest_deprecation(mock_extract, api_client, caplog):
    """Verify that the deprecated /inventory/ingest endpoint returns X-Deprecated header and logs a warning."""
    mock_extract.return_value = {
        "title": "2 BHK Flat",
        "property_type": "apartment",
        "listing_type": "rent",
        "city": "Nashik",
        "area": "Nashik Road",
        "price": 15000,
        "bhk": 2,
        "broker_name": "Test Broker",
        "broker_phone": "9876543210"
    }
    
    with caplog.at_level(logging.WARNING, logger="uvicorn.error"):
        response = api_client.post("/inventory/ingest", json={"raw_message": "2BHK Nashik Road 15k"})
        assert response.status_code == 200
        assert response.headers.get("X-Deprecated") == "true"
        assert "DEPRECATION WARNING" in caplog.text

@patch("apps.api.routers.inventory.extract_property_details")
def test_inventory_ingest_unique(mock_extract, api_client, mock_db):
    """Verify that a unique property ingestion via /inventory/ingest creates a new document."""
    mock_extract.return_value = {
        "title": "2 BHK Flat",
        "property_type": "apartment",
        "listing_type": "rent",
        "city": "Nashik",
        "area": "Nashik Road",
        "price": 15000,
        "bhk": 2,
        "broker_name": "Test Broker",
        "broker_phone": "9876543210"
    }
    
    col = mock_db.client.nph_core.properties
    response = api_client.post("/inventory/ingest", json={"raw_message": "2BHK Nashik Road 15k"})
    assert response.status_code == 200
    assert len(col._docs) == 1
    
    doc = col._docs[0]
    assert doc["availability_status"] == "NEW"
    assert doc["status"] == "ACTIVE"
    assert doc["ingestion_hash"] is not None
    assert doc["intelligence"]["duplicate_count"] == 0

@patch("apps.api.routers.inventory.extract_property_details")
def test_inventory_ingest_duplicate_collision(mock_extract, api_client, mock_db):
    """Verify that a duplicate property ingestion collides and appends to the sources array."""
    from shared.utils.normalization import compute_ingestion_hash
    
    # Pre-calculate ingestion hash for the test entry
    h = compute_ingestion_hash(15000, "Nashik Road", 2, "rent", "9876543210")
    
    col = mock_db.client.nph_core.properties
    existing_doc = {
        "property_id": "prop_existing123",
        "title": "Existing Apartment",
        "city": "Nashik",
        "area": "Nashik Road",
        "price": 15000,
        "bhk": 2,
        "listing_type": "rent",
        "broker_phone": "9876543210",
        "ingestion_hash": h,
        "status": "ACTIVE",
        "sources": [
            {"broker_phone": "9876543210", "group_name": "Group A", "seen_at": "some_time"}
        ],
        "intelligence": {
            "duplicate_count": 0
        }
    }
    col._docs.append(existing_doc)
    
    mock_extract.return_value = {
        "title": "New Listing Title",
        "property_type": "apartment",
        "listing_type": "rent",
        "city": "Nashik",
        "area": "Nashik Road",
        "price": 15000,
        "bhk": 2,
        "broker_name": "Test Broker",
        "broker_phone": "9876543210"
    }
    
    response = api_client.post("/inventory/ingest", json={"raw_message": "2BHK Nashik Road 15k"})
    assert response.status_code == 200
    assert len(col._docs) == 1
    
    doc = col._docs[0]
    assert doc["intelligence"]["duplicate_count"] == 1
    assert len(doc["sources"]) == 2
    assert doc["sources"][1]["broker_phone"] == "9876543210"
    assert doc["sources"][1]["group_name"] == "WhatsApp Intelligence Source"

@pytest.mark.asyncio
@patch("httpx.AsyncClient.post")
async def test_ingest_dump_client_call(mock_post):
    """Verify that ingest_dump.py logs in, then posts the file contents to raw-chunk with the token."""
    login_resp = MagicMock(status_code=200)
    login_resp.json.return_value = {"access_token": "tok123", "token_type": "bearer"}
    ingest_resp = MagicMock(status_code=202)
    ingest_resp.json.return_value = {"status": "accepted"}
    mock_post.side_effect = [login_resp, ingest_resp]

    test_filepath = "temp_unification_messages.txt"
    with open(test_filepath, "w", encoding="utf-8") as f:
        f.write("Test broker WhatsApp group message dump contents.")

    try:
        await ingest_dump.ingest(test_filepath, "Nashik Brokers Premium")
        assert mock_post.call_count == 2
        args, kwargs = mock_post.call_args
        assert args[0].endswith("/properties/raw-chunk")
        assert kwargs["headers"]["Authorization"] == "Bearer tok123"
        assert kwargs["json"]["source_group"] == "Nashik Brokers Premium"
        assert kwargs["json"]["raw_text"] == "Test broker WhatsApp group message dump contents."
    finally:
        if os.path.exists(test_filepath):
            os.remove(test_filepath)

def test_raw_chunk_idempotency_guardrail(api_client, mock_db):
    """Verify that webhook event hash idempotency blocks duplicate raw-chunk payloads."""
    payload = {
        "source_group": "Group Alpha",
        "raw_text": "3BHK Gangapur Road 30k available immediately"
    }
    
    with patch("celery.Celery.send_task") as mock_send:
        mock_send.return_value = MagicMock(id="mock_celery_task_id_456")
        
        # First call succeeds
        response1 = api_client.post("/properties/raw-chunk", json=payload)
        assert response1.status_code == 202
        assert response1.json()["status"] == "accepted"
        
        # Second call returns duplicate skipped
        response2 = api_client.post("/properties/raw-chunk", json=payload)
        assert response2.status_code == 202
        assert response2.json()["status"] == "duplicate_skipped"
