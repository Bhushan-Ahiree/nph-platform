import pytest
from datetime import datetime, timedelta, timezone
from services.property.commission_shield import shield_property
from apps.api.schemas.property_schema_v2 import PropertyPublicResponse
from shared.utils.auth_guard import get_current_user

def test_commission_shield_strips_sensitive_data():
    raw_property = {
        "_id": "prop_test_99",
        "title": "Premium 2BHK flat",
        "area": "Indira Nagar",
        "bhk": 2,
        "price": 18000,
        "building_name": "Balaji Towers",
        "exact_address": "Flat 402, Wing B, Balaji Towers",
        "broker_phone": "919999888877",
        "owner_phone": "918888777766",
        "google_pin": "https://maps.google.com/xyz",
        "availability_status": "VERIFIED",
        "confidence_score": 100
    }
    
    # 1. Assert Customer Boundary (PUBLIC Mode)
    public_variant = shield_property(raw_property, role="PUBLIC")
    assert public_variant["building_name"] == "Hidden until site visit confirmation"
    assert public_variant["exact_address"] == "Hidden until site visit confirmation"
    assert public_variant["broker_phone"] == "Hidden until site visit confirmation"
    assert public_variant["owner_phone"] == "Hidden until site visit confirmation"
    assert public_variant["google_pin"] == "Hidden until site visit confirmation"
    assert "owner_phone" in public_variant # Included but masked!
    assert "match_reason" in public_variant
    assert "status" not in public_variant

    # 2. Assert Operations Boundary (INTERNAL Mode)
    internal_variant = shield_property(raw_property, role="INTERNAL")
    assert internal_variant["building_name"] == "Balaji Towers"
    assert internal_variant["exact_address"] == "Flat 402, Wing B, Balaji Towers"
    assert internal_variant["broker_phone"] == "919999888877"
    assert internal_variant["owner_phone"] == "918888777766"
    assert internal_variant["google_pin"] == "https://maps.google.com/xyz"


@pytest.mark.asyncio
async def test_search_composite_ranking_and_limits(api_client, mock_db):
    """
    GET /properties/search should return top 5 sorted by composite score
    and masked appropriately.
    """
    from apps.api.repositories.property_repository import property_repo
    
    # Setup properties
    col = property_repo.get_collection()
    col._docs = []
    
    # Insert 6 properties to check limit=5 is enforced
    for i in range(1, 7):
        prop = {
            "_id": f"prop_id_{i}",
            "property_id": f"prop_id_{i}",
            "title": f"Test Property {i}",
            "price": 10000 + i * 1000,
            "bhk": 2,
            "area": "Wakad",
            "listing_type": "rent",
            "property_type": "apartment",
            "building_name": f"Balaji Towers {i}",
            "exact_address": f"Flat {i}, Balaji Towers, Wakad",
            "status": "ACTIVE",
            "availability_status": "VERIFIED",
            # Introduce aging to create variance in score ranking: property 1 is fresh, others are older
            "last_verified_at": datetime.now(timezone.utc) - timedelta(days=(i - 1) * 2),
            "confidence_score": 100,
            "broker_phone": "+919999999999",
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc)
        }
        await col.insert_one(prop)

    # Set mock user role dependency override
    api_client.app.dependency_overrides[get_current_user] = lambda: {
        "id": "test_user_id_123",
        "email": "test@nph.com",
        "role": "broker" # broker maps to INTERNAL, exposing names/details
    }

    try:
        # Search as broker (INTERNAL)
        response = api_client.get("/properties/search", params={"area": "Wakad", "bhk": 2, "listing_type": "rent"})
        assert response.status_code == 200
        data = response.json()
        
        # Enforce aggregation limit 5
        assert len(data) == 5
        
        # Check composite scoring sort: i=1 has 0 days_since (no penalty), i=6 has 10 days_since (large penalty)
        # So prop_id_1 must rank first
        assert data[0]["property_id"] == "prop_id_1"
        
        # As INTERNAL role, building name and address should NOT be masked
        assert data[0]["building_name"] != "Hidden until site visit confirmation"

        # Change role override to client (PUBLIC)
        api_client.app.dependency_overrides[get_current_user] = lambda: {
            "id": "test_user_id_123",
            "email": "test@nph.com",
            "role": "client" # client maps to PUBLIC
        }

        # Search as client (PUBLIC)
        response_pub = api_client.get("/properties/search", params={"area": "Wakad", "bhk": 2, "listing_type": "rent"})
        assert response_pub.status_code == 200
        data_pub = response_pub.json()
        
        # Public payload details MUST be masked
        assert data_pub[0]["building_name"] == "Hidden until site visit confirmation"
        assert data_pub[0]["exact_address"] == "Hidden until site visit confirmation"
        assert data_pub[0]["broker_phone"] == "Hidden until site visit confirmation"

    finally:
        api_client.app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_lead_aware_matches_shielded_and_persisted(api_client, mock_db):
    """
    GET /matches/lead/{lead_id} should return matches and log to recommendation events.
    """
    # 1. Setup mock lead
    lead = {
        "id": "lead_user_88",
        "name": "Arjun Patel",
        "requirements": {
            "area": "Wakad",
            "bhk": 2,
            "listing_type": "rent",
            "max_price": 20000
        }
    }
    await mock_db.client.nph_core.leads.insert_one(lead)

    # 2. Setup mock property
    from apps.api.repositories.property_repository import property_repo
    col = property_repo.get_collection()
    col._docs = []
    
    prop = {
        "_id": "prop_match_88",
        "property_id": "prop_match_88",
        "title": "Arjun Matching Apartment",
        "price": 15000,
        "bhk": 2,
        "area": "Wakad",
        "listing_type": "rent",
        "property_type": "apartment",
        "status": "ACTIVE",
        "availability_status": "VERIFIED",
        "confidence_score": 100,
        "broker_phone": "+919999999999",
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc)
    }
    await col.insert_one(prop)

    # Set mock user role dependency override to client (PUBLIC)
    api_client.app.dependency_overrides[get_current_user] = lambda: {
        "id": "test_user_id_123",
        "email": "test@nph.com",
        "role": "client"
    }

    try:
        response = api_client.get("/matches/lead/lead_user_88")
        assert response.status_code == 200
        data = response.json()
        
        # Verify matching property is returned
        assert len(data) == 1
        assert data[0]["property_id"] == "prop_match_88"
        assert data[0]["price"] == 15000
        
        # Verify details are shielded
        assert data[0]["building_name"] == "Hidden until site visit confirmation"
        
        # Verify transaction logged in recommendation events
        rec = await mock_db.client.nph_core.recommendation_events.find_one({"lead_id": "lead_user_88"})
        assert rec is not None
        assert rec["property_id"] == "prop_match_88"
        assert rec["event"] == "SENT"

    finally:
        api_client.app.dependency_overrides.clear()
