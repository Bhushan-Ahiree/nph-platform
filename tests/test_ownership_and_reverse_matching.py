# tests/test_ownership_and_reverse_matching.py
import pytest
from unittest.mock import patch, MagicMock, ANY
from datetime import datetime, timezone
from services.matching.engine import calculate_base_structural_match_score, find_matches_for_lead
from shared.utils.normalization import normalise_extracted_property
from apps.worker.tasks.ingestion_tasks import notify_matching_leads

@pytest.fixture(autouse=True)
def patch_task_db(mock_db):
    """
    Redirects the task modules' MongoClient to the in-memory mock database.
    """
    class MockMongoClient:
        def __init__(self, *args, **kwargs):
            pass
        def __getitem__(self, db_name):
            return mock_db.client[db_name]
        def close(self):
            pass

    with (
        patch("apps.worker.tasks.ingestion_tasks.MongoClient", MockMongoClient),
        patch("apps.worker.tasks.maintenance_tasks.MongoClient", MockMongoClient),
    ):
        yield

def test_ownership_type_normalization():
    # 1. Test owner normalization
    raw_prop_owner = {
        "title": "2 BHK Apartment in Indira Nagar",
        "description": "direct owner",
        "property_type": "apartment",
        "listing_type": "rent",
        "city": "Nashik",
        "area": "Indira Nagar",
        "bhk": 2,
        "price": 12000,
        "broker_phone": "9876543210",
        "ownership_type": "owner"
    }
    norm_owner = normalise_extracted_property(raw_prop_owner, "Test Group", "hash123")
    assert norm_owner["ownership_type"] == "owner"
    assert norm_owner["source"]["type"] == "owner_network"

    # 2. Test broker normalization
    raw_prop_broker = {
        "title": "2 BHK Apartment in Indira Nagar",
        "description": "some text",
        "property_type": "apartment",
        "listing_type": "rent",
        "city": "Nashik",
        "area": "Indira Nagar",
        "bhk": 2,
        "price": 12000,
        "broker_phone": "9876543210",
        "ownership_type": "broker"
    }
    norm_broker = normalise_extracted_property(raw_prop_broker, "Test Group", "hash123")
    assert norm_broker["ownership_type"] == "broker"
    assert norm_broker["source"]["type"] == "broker_group"

def test_base_structural_match_score_with_ownership():
    # Owner bonus = 30
    prop_owner = {
        "area": "Indira Nagar",
        "bhk": 2,
        "price": 12000,
        "parking": True,
        "ownership_type": "owner"
    }
    reqs = {
        "area": "Indira Nagar",
        "bhk": 2,
        "max_price": 15000,
        "parking": True
    }
    # 40 area + 30 price + 20 bhk + 10 parking + 30 owner = 130
    score = calculate_base_structural_match_score(prop_owner, reqs)
    assert score == 130

    # Verified broker bonus = 15
    prop_verified = {
        "area": "Indira Nagar",
        "bhk": 2,
        "price": 12000,
        "parking": True,
        "ownership_type": "verified_broker"
    }
    # 40 + 30 + 20 + 10 + 15 = 115
    score_v = calculate_base_structural_match_score(prop_verified, reqs)
    assert score_v == 115

    # Standard broker bonus = 0
    prop_broker = {
        "area": "Indira Nagar",
        "bhk": 2,
        "price": 12000,
        "parking": True,
        "ownership_type": "broker"
    }
    # 40 + 30 + 20 + 10 + 0 = 100
    score_b = calculate_base_structural_match_score(prop_broker, reqs)
    assert score_b == 100

@pytest.mark.asyncio
async def test_find_matches_for_lead_with_boosts(mock_db):
    from apps.api.repositories.property_repository import property_repo
    col_props = property_repo.get_collection()
    col_props._docs = []

    # Insert 3 properties with different ownership types, same structural attributes
    prop_owner = {
        "property_id": "prop_owner",
        "title": "Owner Prop",
        "area": "Indira Nagar",
        "bhk": 2,
        "price": 12000,
        "listing_type": "rent",
        "status": "ACTIVE",
        "ownership_type": "owner",
        "broker_phone": "9999999999",
        "confidence_score": 100,
        "last_verified_at": datetime.now(timezone.utc)
    }
    prop_verified = {
        "property_id": "prop_verified",
        "title": "Verified Broker Prop",
        "area": "Indira Nagar",
        "bhk": 2,
        "price": 12000,
        "listing_type": "rent",
        "status": "ACTIVE",
        "ownership_type": "broker",
        "broker_phone": "8888888888", # we will set this broker profile to verified=True in DB
        "confidence_score": 100,
        "last_verified_at": datetime.now(timezone.utc)
    }
    prop_broker = {
        "property_id": "prop_broker",
        "title": "Broker Prop",
        "area": "Indira Nagar",
        "bhk": 2,
        "price": 12000,
        "listing_type": "rent",
        "status": "ACTIVE",
        "ownership_type": "broker",
        "broker_phone": "7777777777",
        "confidence_score": 100,
        "last_verified_at": datetime.now(timezone.utc)
    }
    await col_props.insert_one(prop_owner)
    await col_props.insert_one(prop_verified)
    await col_props.insert_one(prop_broker)

    # Mark 8888888888 as verified broker in broker_profiles
    col_brokers = mock_db.client.nph_core.broker_profiles
    col_brokers._docs = [
        {"_id": "8888888888", "verified": True, "reliability_score": 100},
        {"_id": "7777777777", "verified": False, "reliability_score": 100},
    ]

    lead_data = {
        "area": "Indira Nagar",
        "bhk": 2,
        "listing_type": "rent",
        "max_price": 15000
    }

    matches = await find_matches_for_lead(lead_data)
    assert len(matches) == 3
    # Matches should be ordered by ownership type: owner (+30) > verified (+15) > broker (+0)
    assert matches[0]["property_id"] == "prop_owner"
    assert matches[1]["property_id"] == "prop_verified"
    assert matches[2]["property_id"] == "prop_broker"

@pytest.mark.asyncio
async def test_notify_matching_leads_reverse_matching(mock_db):
    col_leads = mock_db.client.nph_core.leads
    col_leads._docs = [
        {
            "id": "lead_notify_1",
            "status": "MATCHABLE",
            "requirements": {
                "area": "Indira Nagar",
                "bhk": 2,
                "listing_type": "rent",
                "max_price": 15000
            }
        }
    ]

    col_props = mock_db.client.nph_core.properties
    col_props._docs = []

    mock_send_whatsapp = MagicMock()
    with patch("apps.worker.tasks.whatsapp_tasks.send_whatsapp_message") as mock_send_task:
        mock_send_task.delay = mock_send_whatsapp
        # Call Celery task directly
        property_doc = {
            "property_id": "prop_new_match",
            "area": "Indira Nagar",
            "bhk": 2,
            "listing_type": "rent",
            "price": 12000,
            "ownership_type": "owner",
            "broker_phone": "9999999999"
        }
        await col_props.insert_one(property_doc)

        notify_matching_leads(property_doc)

        # 1. Lead must be updated to PROPERTIES_SENT status
        updated_lead = await col_leads.find_one({"id": "lead_notify_1"})
        assert updated_lead is not None
        assert updated_lead["status"] == "PROPERTIES_SENT"
        assert updated_lead["last_properties_sent"] == ["prop_new_match"]

        # 2. Match doc must be inserted in matches
        col_matches = mock_db.client.nph_core.matches
        match = await col_matches.find_one({"lead_id": "lead_notify_1"})
        assert match is not None
        assert match["property_ids"] == ["prop_new_match"]

        # 3. WhatsApp notification must be triggered
        mock_send_whatsapp.assert_called_once_with("lead_notify_1", ANY)
