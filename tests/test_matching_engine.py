# tests/test_matching_engine.py
"""
Tests for services/matching/engine.py — the property matching and scoring engine.
"""
import pytest
from datetime import datetime, timezone, timedelta


class TestCalculateMatchScore:
    """Validates the deterministic scoring algorithm."""

    def test_base_score(self):
        from services.matching.engine import calculate_match_score
        # Property with no useful data should get base score
        score = calculate_match_score({}, 0)
        # Base 50 + 10 fallback (no updated_at) + 15 fallback (no price/budget)
        assert score == 75

    def test_fresh_property_full_points(self):
        from services.matching.engine import calculate_match_score
        score = calculate_match_score({
            "updated_at": datetime.now(timezone.utc),
            "price": 12000,
        }, 15000)
        # Base 50 + 20 freshness + 30 budget (12000/15000 = 0.8 in 0.6-0.85 range)
        assert score >= 80

    def test_stale_property_no_freshness(self):
        from services.matching.engine import calculate_match_score
        score = calculate_match_score({
            "updated_at": datetime.now(timezone.utc) - timedelta(days=15),
            "price": 14000,
        }, 15000)
        # Freshness = max(0, 20 - 30) = 0
        # Budget = 14000/15000 = 0.93 => 30 points
        # Total = 50 + 0 + 30 = 80
        assert score == 80

    def test_perfect_budget_fit(self):
        from services.matching.engine import calculate_match_score
        score = calculate_match_score({
            "updated_at": datetime.now(timezone.utc),
            "price": 14000,
        }, 15000)
        # Price ratio = 14000/15000 = 0.93 => perfect fit => 30 pts
        assert score == 100

    def test_good_budget_fit(self):
        from services.matching.engine import calculate_match_score
        score = calculate_match_score({
            "updated_at": datetime.now(timezone.utc),
            "price": 10000,
        }, 15000)
        # Price ratio = 10000/15000 = 0.67 => good deal => 15 pts
        assert score == 85

    def test_cheap_property_no_budget_points(self):
        from services.matching.engine import calculate_match_score
        score = calculate_match_score({
            "updated_at": datetime.now(timezone.utc),
            "price": 5000,
        }, 15000)
        # Price ratio = 5000/15000 = 0.33 => too cheap => 0 pts
        assert score == 70

    def test_score_capped_at_100(self):
        from services.matching.engine import calculate_match_score
        score = calculate_match_score({
            "updated_at": datetime.now(timezone.utc),
            "price": 14500,
        }, 15000)
        assert score <= 100

    def test_naive_datetime_handled(self):
        """Ensures timezone-naive datetimes don't crash the engine."""
        from services.matching.engine import calculate_match_score
        score = calculate_match_score({
            "updated_at": datetime.utcnow(),  # Naive datetime
            "price": 12000,
        }, 15000)
        assert score > 0


class TestMaskPropertyForClient:
    """Validates the commission protection masking function."""

    def test_mask_hides_broker_info(self):
        from services.matching.engine import mask_property_for_client
        full_property = {
            "title": "2 BHK in Indira Nagar",
            "bhk": 2,
            "price": 15000,
            "area": "Indira Nagar",
            "source": {"broker_name": "Rajesh", "broker_phone": "9876543210"},
            "rental_details": {"deposit": 30000, "furnishing": "semi-furnished", "preferred_tenant": "family"},
            "match_score": 90,
        }
        masked = mask_property_for_client(full_property)
        assert "broker_name" not in masked
        assert "broker_phone" not in masked
        assert "source" not in masked
        assert masked["title"] == "2 BHK in Indira Nagar"
        assert masked["general_area"] == "Indira Nagar"
        assert masked["match_score"] == 90

    def test_mask_includes_essential_fields(self):
        from services.matching.engine import mask_property_for_client
        masked = mask_property_for_client({
            "title": "Test",
            "bhk": 3,
            "price": 25000,
            "area": "College Road",
            "rental_details": {"deposit": 50000, "furnishing": "furnished", "preferred_tenant": "any"},
        })
        assert "title" in masked
        assert "bhk" in masked
        assert "price" in masked
        assert "general_area" in masked
        assert "furnishing" in masked


class TestRecommendationPersistence:
    """Validates the Matches/Recommendations database operations and status transitions."""

    @pytest.mark.asyncio
    async def test_insert_match(self, mock_db):
        from apps.api.repositories.match_repository import MatchRepository
        repo = MatchRepository()
        match = await repo.insert_match(
            lead_id="9876543210",
            property_ids=["prop_1", "prop_2"],
            status="SENT"
        )
        assert match is not None
        assert match["lead_id"] == "9876543210"
        assert match["property_ids"] == ["prop_1", "prop_2"]
        assert match["status"] == "SENT"
        assert "match_id" in match

    @pytest.mark.asyncio
    async def test_get_matches_by_lead(self, mock_db):
        from apps.api.repositories.match_repository import MatchRepository
        repo = MatchRepository()
        await repo.insert_match("9876543210", ["prop_1"], "SENT")
        await repo.insert_match("9876543210", ["prop_2"], "SENT")
        results = await repo.get_matches_by_lead("9876543210")
        assert len(results) == 2
        assert len(results[0]["property_ids"]) == 1

    @pytest.mark.asyncio
    async def test_update_match_status(self, mock_db):
        from apps.api.repositories.match_repository import MatchRepository
        repo = MatchRepository()
        match = await repo.insert_match("9876543210", ["prop_1"], "SENT")
        updated = await repo.update_match_status(match["match_id"], "VIEWED")
        assert updated is not None
        assert updated["status"] == "VIEWED"

    @pytest.mark.asyncio
    async def test_filter_previously_sent_properties(self, mock_db):
        collection = mock_db.client.nph_core.matches
        await collection.insert_one({
            "match_id": "match_legacy",
            "lead_id": "9876543210",
            "property_ids": ["prop_already_sent"],
            "status": "SENT",
            "generated_at": datetime.now(timezone.utc)
        })

        matches_surfaced = [
            {"property_id": "prop_already_sent", "bhk": 2, "area": "Indira Nagar", "price": 1000},
            {"property_id": "prop_fresh", "bhk": 2, "area": "Indira Nagar", "price": 1000}
        ]

        historical_matches = await collection.find({"lead_id": "9876543210"}).to_list(length=10)
        sent_property_ids = set()
        for hm in historical_matches:
            sent_property_ids.update(hm.get("property_ids", []))

        fresh_matches = [m for m in matches_surfaced if m.get("property_id") not in sent_property_ids]
        
        assert len(fresh_matches) == 1
        assert fresh_matches[0]["property_id"] == "prop_fresh"

