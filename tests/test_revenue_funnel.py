# tests/test_revenue_funnel.py
import pytest
from datetime import datetime, timezone
from shared.utils.auth_guard import get_current_user

@pytest.mark.asyncio
async def test_search_and_match_dynamic_role_serialization(api_client, mock_db):
    """
    Search and matching endpoints must enforce dynamic role-based serialization wrappers:
    - PUBLIC users get masked PropertyPublicResponse schemas.
    - INTERNAL/ADMIN users get unmasked PropertyInternalResponse schemas.
    """
    # 1. Setup mock property in database
    from apps.api.repositories.property_repository import property_repo
    col = property_repo.get_collection()
    col._docs = []
    
    prop = {
        "_id": "prop_funnel_1",
        "property_id": "prop_funnel_1",
        "title": "Funnel Luxury Villa",
        "price": 50000,
        "bhk": 4,
        "area": "Kothrud",
        "listing_type": "rent",
        "property_type": "villa",
        "building_name": "Skyline Heights",
        "exact_address": "Penthouse 1, Skyline Heights, Kothrud",
        "broker_phone": "+919876543210",
        "owner_phone": "+919999999999",
        "google_pin": "https://maps.google.com/pin",
        "status": "ACTIVE",
        "availability_status": "VERIFIED",
        "confidence_score": 100,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc)
    }
    await col.insert_one(prop)
    
    # 2. Assert PUBLIC role constraints
    api_client.app.dependency_overrides[get_current_user] = lambda: {
        "id": "user_public",
        "email": "public@nph.com",
        "role": "client"
    }
    
    try:
        response_pub = api_client.get("/properties/search", params={
            "area": "Kothrud",
            "bhk": 4,
            "listing_type": "rent"
        })
        assert response_pub.status_code == 200
        data_pub = response_pub.json()
        assert len(data_pub) == 1
        assert data_pub[0]["building_name"] == "Hidden until site visit confirmation"
        assert data_pub[0]["exact_address"] == "Hidden until site visit confirmation"
        assert data_pub[0]["broker_phone"] == "Hidden until site visit confirmation"
        assert data_pub[0]["owner_phone"] == "Hidden until site visit confirmation"
        assert data_pub[0]["google_pin"] == "Hidden until site visit confirmation"
        
        # 3. Assert INTERNAL role access
        api_client.app.dependency_overrides[get_current_user] = lambda: {
            "id": "user_internal",
            "email": "internal@nph.com",
            "role": "broker"
        }
        
        response_int = api_client.get("/properties/search", params={
            "area": "Kothrud",
            "bhk": 4,
            "listing_type": "rent"
        })
        assert response_int.status_code == 200
        data_int = response_int.json()
        assert len(data_int) == 1
        assert data_int[0]["building_name"] == "Skyline Heights"
        assert data_int[0]["exact_address"] == "Penthouse 1, Skyline Heights, Kothrud"
        assert data_int[0]["broker_phone"] == "+919876543210"
        assert data_int[0]["owner_phone"] == "+919999999999"
        assert data_int[0]["google_pin"] == "https://maps.google.com/pin"
        
    finally:
        api_client.app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_recommendation_history_logging_on_matching(api_client, mock_db):
    """
    Lead matching endpoint must persist SENT events into recommendation_events collection.
    """
    # 1. Setup mock lead
    lead = {
        "id": "lead_rec_test",
        "name": "Arjun Patel",
        "requirements": {
            "city": "Nashik",
            "area": "Kothrud",
            "bhk": 3,
            "listing_type": "rent",
            "max_price": 30000
        }
    }
    await mock_db.client.nph_core.leads.insert_one(lead)
    
    # 2. Setup mock property
    from apps.api.repositories.property_repository import property_repo
    col_prop = property_repo.get_collection()
    col_prop._docs = []
    
    prop = {
        "_id": "prop_rec_1",
        "property_id": "prop_rec_1",
        "title": "Matching Apartment",
        "price": 25000,
        "bhk": 3,
        "area": "Kothrud",
        "listing_type": "rent",
        "property_type": "apartment",
        "status": "ACTIVE",
        "availability_status": "VERIFIED",
        "confidence_score": 100,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc)
    }
    await col_prop.insert_one(prop)
    
    # 3. Setup user context
    api_client.app.dependency_overrides[get_current_user] = lambda: {
        "id": "user_admin",
        "email": "admin@nph.com",
        "role": "admin"
    }
    
    try:
        # Clear past events for clean verification
        mock_db.client.nph_core.recommendation_events._docs = []
        
        response = api_client.get("/matches/lead/lead_rec_test")
        assert response.status_code == 200
        
        # Verify event was logged via repository
        events = mock_db.client.nph_core.recommendation_events._docs
        assert len(events) == 1
        assert events[0]["lead_id"] == "lead_rec_test"
        assert events[0]["property_id"] == "prop_rec_1"
        assert events[0]["event"] == "SENT"
        assert "match_score" in events[0]
        
    finally:
        api_client.app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_deal_closed_cascade_transaction(api_client, mock_db):
    """
    PATCHing site visit status to 'COMPLETED' with 'deal_closed=True' triggers an atomic
    database cascade: site visit monetization populated, lead closed, and property archived.
    """
    # 1. Setup mock lead
    lead = {
        "id": "lead_cascade_1",
        "name": "Cascade Client",
        "status": "DISCOVERY",
        "requirements": {
            "city": "Nashik",
            "area": "Wakad",
            "bhk": 2,
            "listing_type": "rent"
        }
    }
    await mock_db.client.nph_core.leads.insert_one(lead)
    
    # 2. Setup mock property
    from apps.api.repositories.property_repository import property_repo
    col_prop = property_repo.get_collection()
    col_prop._docs = []
    
    prop = {
        "_id": "prop_cascade_1",
        "property_id": "prop_cascade_1",
        "title": "Cascade Apartment",
        "price": 20000,
        "bhk": 2,
        "area": "Wakad",
        "listing_type": "rent",
        "property_type": "apartment",
        "status": "ACTIVE",
        "availability_status": "VERIFIED",
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc)
    }
    await col_prop.insert_one(prop)
    
    # 3. Setup mock site visit
    from apps.api.repositories.site_visit_repository import site_visit_repo
    col_sv = site_visit_repo.collection
    col_sv._docs = []
    
    visit = await site_visit_repo.insert_site_visit(
        lead_id="lead_cascade_1",
        property_id="prop_cascade_1",
        scheduled_at=datetime.now(timezone.utc),
        notes="Awaiting closing"
    )
    visit_id = visit["id"]
    
    # 4. Trigger showing update with deal_closed=True
    payload = {
        "status": "COMPLETED",
        "deal_closed": True,
        "visit_fee": 150,
        "fee_collected": True,
        "collected_by": "mother",
        "visit_result": "interested"
    }
    
    response = api_client.patch(f"/site-visits/{visit_id}", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "COMPLETED"
    assert data["deal_closed"] is True
    assert data["visit_fee"] == 150
    assert data["fee_collected"] is True
    assert data["collected_by"] == "mother"
    assert data["visit_result"] == "interested"
    
    # 5. Verify database cascades occurred
    # Lead must be CLOSED
    updated_lead = await mock_db.client.nph_core.leads.find_one({"id": "lead_cascade_1"})
    assert updated_lead is not None
    assert updated_lead["status"] == "CLOSED"
    
    # Property must be ARCHIVED (status and availability_status)
    updated_prop = await mock_db.client.nph_core.properties.find_one({"property_id": "prop_cascade_1"})
    assert updated_prop is not None
    assert updated_prop["status"] == "ARCHIVED"
    assert updated_prop["availability_status"] == "ARCHIVED"
