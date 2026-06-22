# tests/test_broker_profile.py
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

@pytest.fixture(autouse=True)
def mock_pymongo_client(mock_db):
    """
    Redirect MongoClient inside Celery tasks to use the mock DB client
    so that background sweeps query the in-memory mock collections.
    """
    with patch("apps.worker.tasks.maintenance_tasks.MongoClient") as mock_client_class:
        mock_client_class.return_value = mock_db.client
        yield

@pytest.mark.asyncio
async def test_broker_repository_operations(mock_db):
    """Verifies standard lookup, counter updates, and reliability score recalculations."""
    from apps.api.repositories.broker_repository import broker_repo

    # 1. Upsert a broker profile
    broker = await broker_repo.upsert_broker(phone="+919999999999", name="Rajesh Kumar", company="Rajesh Realty")
    assert broker is not None
    assert broker["phone"] == "+919999999999"
    assert broker["name"] == "Rajesh Kumar"
    assert broker["reliability_score"] == 100

    # 2. Increment properties_posted (verified = 0, posted = 1 -> 0% reliability)
    updated = await broker_repo.increment_property_counter("+919999999999", "properties_posted")
    assert updated["properties_posted"] == 1
    assert updated["reliability_score"] == 0

    # 3. Increment verified_properties (verified = 1, posted = 1 -> 100% reliability)
    updated = await broker_repo.increment_property_counter("+919999999999", "verified_properties")
    assert updated["verified_properties"] == 1
    assert updated["reliability_score"] == 100

    # 4. Increment properties_posted again (verified = 1, posted = 2 -> 50% reliability)
    updated = await broker_repo.increment_property_counter("+919999999999", "properties_posted")
    assert updated["properties_posted"] == 2
    assert updated["reliability_score"] == 50


@pytest.mark.asyncio
async def test_weighted_matching_sorting(mock_db):
    """Verifies that the refactored matching engine ranks listings correctly using the composite score formula."""
    from apps.api.repositories.property_repository import property_repo
    from apps.api.repositories.broker_repository import broker_repo
    from services.matching.engine import find_matches_for_lead

    # Setup broker profiles
    await broker_repo.upsert_broker(phone="+911111111111", name="Broker Good")  # reliability = 100
    await mock_db.client.nph_core.broker_profiles.find_one_and_update(
        {"_id": "+912222222222"},
        {"$set": {"phone": "+912222222222", "name": "Broker Bad", "reliability_score": 20}},
        upsert=True
    )

    col = property_repo.get_collection()
    col._docs = []

    # 1. Fresh property with Good Broker (Score: 100 + 100 + 100 = 300)
    prop_good = {
        "property_id": "prop_good",
        "title": "Good Broker Apt",
        "bhk": 2,
        "area": "Wakad",
        "price": 15000,
        "listing_type": "rent",
        "status": "ACTIVE",
        "broker_phone": "+911111111111",
        "confidence_score": 100,
        "last_verified_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc)
    }

    # 2. Fresh property with Bad Broker (Score: 100 + 100 + 20 = 220)
    prop_bad = {
        "property_id": "prop_bad",
        "title": "Bad Broker Apt",
        "bhk": 2,
        "area": "Wakad",
        "price": 15000,
        "listing_type": "rent",
        "status": "ACTIVE",
        "broker_phone": "+912222222222",
        "confidence_score": 100,
        "last_verified_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc)
    }

    # 3. Stale property with Good Broker (Score: 100 + (100 - 10 * 5) + 100 = 250)
    prop_stale = {
        "property_id": "prop_stale",
        "title": "Stale Apt Good Broker",
        "bhk": 2,
        "area": "Wakad",
        "price": 15000,
        "listing_type": "rent",
        "status": "ACTIVE",
        "broker_phone": "+911111111111",
        "confidence_score": 100,
        "last_verified_at": datetime.now(timezone.utc) - timedelta(days=10),
        "updated_at": datetime.now(timezone.utc)
    }

    await col.insert_one(prop_good)
    await col.insert_one(prop_bad)
    await col.insert_one(prop_stale)

    lead_data = {
        "bhk": 2,
        "area": "Wakad",
        "listing_type": "rent",
        "max_price": 20000
    }

    matches = await find_matches_for_lead(lead_data)
    assert len(matches) == 3
    # Ranks should follow: prop_good (300) -> prop_stale (250) -> prop_bad (220)
    assert matches[0]["property_id"] == "prop_good"
    assert matches[1]["property_id"] == "prop_stale"
    assert matches[2]["property_id"] == "prop_bad"


@pytest.mark.asyncio
async def test_verify_endpoint_upgrades_broker_counters(api_client, mock_db):
    """Verifies verify endpoint resets confidence score and increments broker verified property count."""
    from apps.api.repositories.property_repository import property_repo
    from shared.utils.auth_guard import get_current_user

    api_client.app.dependency_overrides[get_current_user] = lambda: {
        "id": "admin_user",
        "email": "admin@nph.com",
        "role": "admin"
    }

    try:
        col = property_repo.get_collection()
        col._docs = []
        
        prop = {
            "property_id": "prop_verify_test",
            "title": "Verify Target Apt",
            "bhk": 2,
            "area": "Kothrud",
            "listing_type": "rent",
            "price": 12000,
            "status": "UNVERIFIED",
            "availability_status": "stale",
            "verification_count": 1,
            "confidence_score": 40,
            "broker_phone": "+913333333333",
            "last_verified_at": datetime.now(timezone.utc) - timedelta(days=10),
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc)
        }
        await col.insert_one(prop)

        headers = {"Authorization": "Bearer token"}
        response = api_client.patch("/properties/prop_verify_test/verify", headers=headers)
        assert response.status_code == 200
        data = response.json()
        
        # Check updated property fields
        assert data["status"] == "ACTIVE"
        assert data["availability_status"] == "VERIFIED"
        assert data["verification_count"] == 2
        assert data["confidence_score"] == 100

        # Check corresponding broker profile verified_properties count
        broker = await mock_db.client.nph_core.broker_profiles.find_one({"_id": "+913333333333"})
        assert broker is not None
        assert broker["verified_properties"] == 1
    finally:
        api_client.app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_sweeper_decrements_confidence_and_increments_expired(mock_db):
    """Verifies that Celery sweeper decrements stale confidence scores and increments broker expired properties."""
    from apps.api.repositories.property_repository import property_repo
    from apps.worker.tasks.maintenance_tasks import sweep_inventory_freshness

    col = property_repo.get_collection()
    col._docs = []

    stale_rent = {
        "title": "Stale Rent Apartment",
        "price": 12000,
        "area": "Indira Nagar",
        "listing_type": "rent",
        "property_type": "apartment",
        "status": "ACTIVE",
        "availability_status": "verified",
        "confidence_score": 100,
        "broker_phone": "+914444444444",
        "created_at": datetime.now(timezone.utc) - timedelta(days=10),
        "updated_at": datetime.now(timezone.utc) - timedelta(days=10)
    }
    await col.insert_one(stale_rent)

    expired_rent = {
        "title": "Expired Rent Apartment",
        "price": 12000,
        "area": "Indira Nagar",
        "listing_type": "rent",
        "property_type": "apartment",
        "status": "ACTIVE",
        "availability_status": "verified",
        "confidence_score": 100,
        "broker_phone": "+914444444444",
        "created_at": datetime.now(timezone.utc) - timedelta(days=20),
        "updated_at": datetime.now(timezone.utc) - timedelta(days=20)
    }
    await col.insert_one(expired_rent)

    sweep_inventory_freshness()

    res_stale = await col.find_one({"title": "Stale Rent Apartment"})
    assert res_stale["status"] == "ACTIVE"
    assert res_stale["availability_status"] == "UNVERIFIED"
    assert res_stale["confidence_score"] == 90

    res_expired = await col.find_one({"title": "Expired Rent Apartment"})
    assert res_expired["status"] == "ARCHIVED"
    assert res_expired["availability_status"] == "ARCHIVED"

    broker = await mock_db.client.nph_core.broker_profiles.find_one({"_id": "+914444444444"})
    assert broker is not None
    assert broker["expired_properties"] == 1
