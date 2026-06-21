# tests/test_inventory_engine.py
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
async def test_freshness_sweeper_asymmetric_rent(mock_db):
    """
    Rent properties older than 7 days transition to UNVERIFIED,
    while fresh ones remain ACTIVE.
    """
    from apps.api.repositories.property_repository import property_repo
    from apps.worker.tasks.maintenance_tasks import sweep_inventory_freshness

    # 1. Stale Rent Property (10 days old)
    stale_rent = {
        "title": "Stale Rent Apartment",
        "price": 12000,
        "area": "Indira Nagar",
        "listing_type": "rent",
        "property_type": "apartment",
        "status": "ACTIVE",
        "created_at": datetime.now(timezone.utc) - timedelta(days=10),
        "updated_at": datetime.now(timezone.utc) - timedelta(days=10)
    }
    # 2. Fresh Rent Property (3 days old)
    fresh_rent = {
        "title": "Fresh Rent Apartment",
        "price": 15000,
        "area": "Indira Nagar",
        "listing_type": "rent",
        "property_type": "apartment",
        "status": "ACTIVE",
        "created_at": datetime.now(timezone.utc) - timedelta(days=3),
        "updated_at": datetime.now(timezone.utc) - timedelta(days=3)
    }

    col = property_repo.get_collection()
    col._docs = []  # Clear for isolation
    await col.insert_one(stale_rent)
    await col.insert_one(fresh_rent)

    # Run the sweeper
    sweep_inventory_freshness()

    stale_res = await col.find_one({"title": "Stale Rent Apartment"})
    fresh_res = await col.find_one({"title": "Fresh Rent Apartment"})

    assert stale_res["status"] == "UNVERIFIED"
    assert fresh_res["status"] == "ACTIVE"


@pytest.mark.asyncio
async def test_freshness_sweeper_asymmetric_sale_flat_commercial(mock_db):
    """
    Sale flats or commercial listings older than 60 days transition to UNVERIFIED.
    """
    from apps.api.repositories.property_repository import property_repo
    from apps.worker.tasks.maintenance_tasks import sweep_inventory_freshness

    col = property_repo.get_collection()
    col._docs = []

    # Stale flat sale (65 days old)
    stale_flat = {
        "title": "Stale Sale Flat",
        "price": 5000000,
        "area": "Kothrud",
        "listing_type": "sale",
        "property_type": "flat",
        "status": "ACTIVE",
        "created_at": datetime.now(timezone.utc) - timedelta(days=65),
        "updated_at": datetime.now(timezone.utc) - timedelta(days=65)
    }
    # Fresh commercial sale (40 days old)
    fresh_commercial = {
        "title": "Fresh Sale Commercial",
        "price": 8000000,
        "area": "College Road",
        "listing_type": "sale",
        "property_type": "commercial",
        "status": "ACTIVE",
        "created_at": datetime.now(timezone.utc) - timedelta(days=40),
        "updated_at": datetime.now(timezone.utc) - timedelta(days=40)
    }

    await col.insert_one(stale_flat)
    await col.insert_one(fresh_commercial)

    sweep_inventory_freshness()

    stale_flat_res = await col.find_one({"title": "Stale Sale Flat"})
    fresh_comm_res = await col.find_one({"title": "Fresh Sale Commercial"})

    assert stale_flat_res["status"] == "UNVERIFIED"
    assert fresh_comm_res["status"] == "ACTIVE"


@pytest.mark.asyncio
async def test_freshness_sweeper_asymmetric_sale_plot_land(mock_db):
    """
    Sale plots or land listings older than 90 days transition to UNVERIFIED.
    """
    from apps.api.repositories.property_repository import property_repo
    from apps.worker.tasks.maintenance_tasks import sweep_inventory_freshness

    col = property_repo.get_collection()
    col._docs = []

    # Stale land sale (95 days old)
    stale_land = {
        "title": "Stale Sale Land",
        "price": 12000000,
        "area": "Pathardi Phata",
        "listing_type": "sale",
        "property_type": "land",
        "status": "ACTIVE",
        "created_at": datetime.now(timezone.utc) - timedelta(days=95),
        "updated_at": datetime.now(timezone.utc) - timedelta(days=95)
    }
    # Fresh plot sale (80 days old)
    fresh_plot = {
        "title": "Fresh Sale Plot",
        "price": 7000000,
        "area": "Adgaon",
        "listing_type": "sale",
        "property_type": "plot",
        "status": "ACTIVE",
        "created_at": datetime.now(timezone.utc) - timedelta(days=80),
        "updated_at": datetime.now(timezone.utc) - timedelta(days=80)
    }

    await col.insert_one(stale_land)
    await col.insert_one(fresh_plot)

    sweep_inventory_freshness()

    stale_land_res = await col.find_one({"title": "Stale Sale Land"})
    fresh_plot_res = await col.find_one({"title": "Fresh Sale Plot"})

    assert stale_land_res["status"] == "UNVERIFIED"
    assert fresh_plot_res["status"] == "ACTIVE"


@pytest.mark.asyncio
async def test_search_and_matching_blocks_non_active(api_client, mock_db):
    """
    Search endpoint and match triggers block UNVERIFIED or ARCHIVED listings.
    """
    from apps.api.repositories.property_repository import property_repo
    col = property_repo.get_collection()
    col._docs = []
    
    # 1. ACTIVE property
    prop_active = {
        "property_id": "prop_act1",
        "title": "Active Apartment",
        "price": 10000,
        "bhk": 2,
        "area": "Indira Nagar",
        "listing_type": "rent",
        "property_type": "apartment",
        "status": "ACTIVE",
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc)
    }
    # 2. UNVERIFIED property
    prop_unverified = {
        "property_id": "prop_unv1",
        "title": "Unverified Apartment",
        "price": 10000,
        "bhk": 2,
        "area": "Indira Nagar",
        "listing_type": "rent",
        "property_type": "apartment",
        "status": "UNVERIFIED",
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc)
    }
    # 3. ARCHIVED property
    prop_archived = {
        "property_id": "prop_arc1",
        "title": "Archived Apartment",
        "price": 10000,
        "bhk": 2,
        "area": "Indira Nagar",
        "listing_type": "rent",
        "property_type": "apartment",
        "status": "ARCHIVED",
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc)
    }
    
    await col.insert_one(prop_active)
    await col.insert_one(prop_unverified)
    await col.insert_one(prop_archived)

    # Call /properties/search
    search_response = api_client.get("/properties/search", params={"area": "Indira Nagar", "bhk": 2})
    assert search_response.status_code == 200
    search_data = search_response.json()["data"]
    
    # Should only return the ACTIVE property
    assert len(search_data) == 1
    assert search_data[0]["property_id"] == "prop_act1"


@pytest.mark.asyncio
async def test_verify_and_archive_endpoints(api_client, mock_db):
    """
    PATCH /properties/{id}/verify sets status to ACTIVE.
    PATCH /properties/{id}/archive sets status to ARCHIVED.
    """
    from apps.api.repositories.property_repository import property_repo
    from shared.utils.auth_guard import get_current_user

    # Bypass Mongo DB user lookup by overriding the authentication dependency
    api_client.app.dependency_overrides[get_current_user] = lambda: {
        "id": "test_user_id_123",
        "email": "test@nph.com",
        "role": "admin"
    }

    try:
        col = property_repo.get_collection()
        col._docs = []

        prop = {
            "property_id": "prop_target123",
            "title": "Target Apartment",
            "price": 15000,
            "bhk": 2,
            "area": "Kothrud",
            "listing_type": "rent",
            "property_type": "apartment",
            "status": "UNVERIFIED",
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc) - timedelta(days=20)
        }
        await col.insert_one(prop)

        headers = {"Authorization": "Bearer dummy_token"}

        # Verify the property
        response_verify = api_client.patch("/properties/prop_target123/verify", headers=headers)
        assert response_verify.status_code == 200
        data_verify = response_verify.json()
        assert data_verify["status"] == "ACTIVE"
        assert datetime.fromisoformat(data_verify["updated_at"].replace("Z", "+00:00")) > datetime.now(timezone.utc) - timedelta(days=5)

        # Archive the property
        response_archive = api_client.patch("/properties/prop_target123/archive", headers=headers)
        assert response_archive.status_code == 200
        data_archive = response_archive.json()
        assert data_archive["status"] == "ARCHIVED"
    finally:
        api_client.app.dependency_overrides.clear()
