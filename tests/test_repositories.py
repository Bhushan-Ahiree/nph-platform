# tests/test_repositories.py
"""
Tests for all repository classes.
Uses the mock MongoDB collections from conftest.py.
"""
import pytest
from datetime import datetime, timezone


class TestUserRepository:
    """Validates apps/api/repositories/user_repository.py."""

    @pytest.mark.asyncio
    async def test_create_user(self, mock_db):
        from apps.api.repositories.user_repository import UserRepository
        repo = UserRepository()
        user_data = {
            "email": "test@nph.com",
            "hashed_password": "hashed_abc",
            "full_name": "Test User",
            "role": "broker",
            "created_at": datetime.now(timezone.utc),
        }
        result = await repo.create(user_data)
        assert result["email"] == "test@nph.com"
        assert "_id" in result

    @pytest.mark.asyncio
    async def test_get_by_email(self, mock_db):
        from apps.api.repositories.user_repository import UserRepository
        repo = UserRepository()
        user_data = {
            "email": "find@nph.com",
            "hashed_password": "hashed_abc",
            "full_name": "Find User",
            "role": "broker",
            "created_at": datetime.now(timezone.utc),
        }
        await repo.create(user_data)
        found = await repo.get_by_email("find@nph.com")
        assert found is not None
        assert found["email"] == "find@nph.com"

    @pytest.mark.asyncio
    async def test_get_by_email_not_found(self, mock_db):
        from apps.api.repositories.user_repository import UserRepository
        repo = UserRepository()
        found = await repo.get_by_email("nonexistent@nph.com")
        assert found is None


class TestLeadRepository:
    """Validates apps/api/repositories/lead_repository.py."""

    @pytest.mark.asyncio
    async def test_insert_lead(self, mock_db):
        from apps.api.repositories.lead_repository import LeadRepository
        from apps.api.schemas.lead_schemas import LeadCreate
        repo = LeadRepository()
        lead = LeadCreate(
            id="9876543210",
            name="Rahul Sharma",
            requirements={
                "city": "Nashik",
                "area": "Indira Nagar",
                "bhk": 2,
                "min_price": 8000,
                "max_price": 15000,
                "property_type": "apartment",
                "listing_type": "rent"
            }
        )
        result = await repo.insert_lead(lead)
        assert result["name"] == "Rahul Sharma"
        assert result["id"] == "9876543210"
        assert result["status"] == "DISCOVERY"

    @pytest.mark.asyncio
    async def test_get_lead_by_id(self, mock_db):
        from apps.api.repositories.lead_repository import LeadRepository
        from apps.api.schemas.lead_schemas import LeadCreate
        repo = LeadRepository()
        lead = LeadCreate(
            id="9876543210",
            name="Test Lead",
            requirements={
                "city": "Nashik",
                "area": "Area",
                "bhk": 2,
                "min_price": 5000,
                "max_price": 10000,
                "property_type": "apartment",
                "listing_type": "rent"
            }
        )
        inserted = await repo.insert_lead(lead)
        found = await repo.get_lead_by_id(inserted["id"])
        assert found is not None
        assert found["name"] == "Test Lead"

    @pytest.mark.asyncio
    async def test_get_all_leads(self, mock_db):
        from apps.api.repositories.lead_repository import LeadRepository
        from apps.api.schemas.lead_schemas import LeadCreate
        repo = LeadRepository()
        for i in range(3):
            lead = LeadCreate(
                id=f"987654321{i}",
                name=f"Lead {i}",
                requirements={
                    "city": "Nashik",
                    "area": "Area",
                    "bhk": 2,
                    "min_price": 5000,
                    "max_price": 10000,
                    "property_type": "apartment",
                    "listing_type": "rent"
                }
            )
            await repo.insert_lead(lead)
        leads = await repo.get_all_leads(limit=10)
        assert len(leads) == 3

    @pytest.mark.asyncio
    async def test_update_lead(self, mock_db):
        from apps.api.repositories.lead_repository import LeadRepository
        from apps.api.schemas.lead_schemas import LeadCreate, LeadUpdate
        repo = LeadRepository()
        lead = LeadCreate(
            id="9876543210",
            name="Original Name",
            requirements={
                "city": "Nashik",
                "area": "Area",
                "bhk": 2,
                "min_price": 5000,
                "max_price": 10000,
                "property_type": "apartment",
                "listing_type": "rent"
            }
        )
        inserted = await repo.insert_lead(lead)
        update = LeadUpdate(name="Updated Name")
        result = await repo.update_lead(inserted["id"], update)
        assert result["name"] == "Updated Name"

    @pytest.mark.asyncio
    async def test_delete_lead(self, mock_db):
        from apps.api.repositories.lead_repository import LeadRepository
        from apps.api.schemas.lead_schemas import LeadCreate
        repo = LeadRepository()
        lead = LeadCreate(
            id="9876543210",
            name="Delete Me",
            requirements={
                "city": "Nashik",
                "area": "Area",
                "bhk": 2,
                "min_price": 5000,
                "max_price": 10000,
                "property_type": "apartment",
                "listing_type": "rent"
            }
        )
        inserted = await repo.insert_lead(lead)
        deleted = await repo.delete_lead(inserted["id"])
        assert deleted is True
        found = await repo.get_lead_by_id(inserted["id"])
        assert found is None

    @pytest.mark.asyncio
    async def test_create_indexes(self, mock_db):
        from apps.api.repositories.lead_repository import LeadRepository
        repo = LeadRepository()
        await repo.create_indexes()



class TestPropertyRepository:
    """Validates apps/api/repositories/property_repository.py."""

    @pytest.mark.asyncio
    async def test_create_property(self, mock_db):
        from apps.api.repositories.property_repository import PropertyRepository
        repo = PropertyRepository()
        prop_data = {
            "property_id": "prop_test123",
            "title": "2 BHK in Indira Nagar",
            "city": "Nashik",
            "area": "Indira Nagar",
            "price": 15000,
            "bhk": 2,
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        }
        result = await repo.create(prop_data)
        assert result["title"] == "2 BHK in Indira Nagar"
        assert "_id" in result

    @pytest.mark.asyncio
    async def test_check_duplicate_found(self, mock_db):
        from apps.api.repositories.property_repository import PropertyRepository
        repo = PropertyRepository()
        await repo.create({
            "property_id": "prop_dup1",
            "title": "2 BHK Flat",
            "city": "Nashik",
            "area": "Indira Nagar",
            "price": 15000,
        })
        dup = await repo.check_duplicate("2 BHK Flat", "Nashik", "Indira Nagar")
        assert dup is not None

    @pytest.mark.asyncio
    async def test_check_duplicate_not_found(self, mock_db):
        from apps.api.repositories.property_repository import PropertyRepository
        repo = PropertyRepository()
        dup = await repo.check_duplicate("Nonexistent", "Nashik", "Test Area")
        assert dup is None

    @pytest.mark.asyncio
    async def test_update_property(self, mock_db):
        from apps.api.repositories.property_repository import PropertyRepository
        repo = PropertyRepository()
        await repo.create({
            "property_id": "prop_update1",
            "title": "Original Title",
            "city": "Nashik",
            "area": "Test",
            "price": 10000,
        })
        result = await repo.update("prop_update1", {"price": 12000})
        assert result is not None
        assert result["price"] == 12000

    @pytest.mark.asyncio
    async def test_delete_property(self, mock_db):
        from apps.api.repositories.property_repository import PropertyRepository
        repo = PropertyRepository()
        await repo.create({
            "property_id": "prop_del1",
            "title": "Delete Me",
            "city": "Nashik",
            "area": "Test",
            "price": 10000,
        })
        success = await repo.delete("prop_del1")
        assert success is True

    @pytest.mark.asyncio
    async def test_delete_nonexistent_property(self, mock_db):
        from apps.api.repositories.property_repository import PropertyRepository
        repo = PropertyRepository()
        success = await repo.delete("prop_nonexistent")
        assert success is False

    @pytest.mark.asyncio
    async def test_find_filtered(self, mock_db):
        from apps.api.repositories.property_repository import PropertyRepository
        repo = PropertyRepository()
        for i in range(5):
            await repo.create({
                "property_id": f"prop_filter{i}",
                "title": f"Flat {i}",
                "city": "Nashik",
                "area": "Indira Nagar",
                "bhk": 2,
                "price": 10000 + (i * 1000),
                "updated_at": datetime.now(timezone.utc),
            })
        results = await repo.find_filtered({"bhk": 2}, limit=3)
        assert len(results) == 3


class TestMatchRepository:
    """Validates apps/api/repositories/match_repository.py."""

    @pytest.mark.asyncio
    async def test_insert_match(self, mock_db):
        from apps.api.repositories.match_repository import MatchRepository
        repo = MatchRepository()
        result = await repo.insert_match(
            lead_id="lead_abc",
            property_ids=["prop_xyz", "prop_123"],
            status="SENT"
        )
        assert result is not None
        assert result["lead_id"] == "lead_abc"
        assert result["property_ids"] == ["prop_xyz", "prop_123"]
        assert result["status"] == "SENT"
        assert "match_id" in result
        assert "generated_at" in result

    @pytest.mark.asyncio
    async def test_get_matches_by_lead(self, mock_db):
        import asyncio
        from apps.api.repositories.match_repository import MatchRepository
        repo = MatchRepository()
        await repo.insert_match("lead_abc", ["prop_1"], "SENT")
        await asyncio.sleep(0.02)
        await repo.insert_match("lead_abc", ["prop_2"], "SENT")
        result = await repo.get_matches_by_lead("lead_abc")
        assert len(result) == 2
        assert result[0]["property_ids"] == ["prop_2"]
        assert result[1]["property_ids"] == ["prop_1"]

    @pytest.mark.asyncio
    async def test_update_match_status(self, mock_db):
        from apps.api.repositories.match_repository import MatchRepository
        repo = MatchRepository()
        match = await repo.insert_match("lead_abc", ["prop_1"], "SENT")
        updated = await repo.update_match_status(match["match_id"], "VIEWED")
        assert updated is not None
        assert updated["status"] == "VIEWED"
        assert updated["match_id"] == match["match_id"]

    @pytest.mark.asyncio
    async def test_create_indexes(self, mock_db):
        from apps.api.repositories.match_repository import MatchRepository
        repo = MatchRepository()
        await repo.create_indexes()


class TestConversationRepository:
    """Validates apps/api/repositories/conversation_repository.py."""

    @pytest.mark.asyncio
    async def test_append_message(self, mock_db):
        from apps.api.repositories.conversation_repository import ConversationRepository
        from apps.api.schemas.conversation_schemas import ConversationAppend
        repo = ConversationRepository()
        msg = ConversationAppend(role="user", content="I need 2 BHK flat")
        result = await repo.append_message_to_history("lead_conv1", "9876543210", msg)
        assert result is not None
        assert result["lead_id"] == "lead_conv1"
        assert len(result["messages"]) == 1

    @pytest.mark.asyncio
    async def test_append_multiple_messages(self, mock_db):
        from apps.api.repositories.conversation_repository import ConversationRepository
        from apps.api.schemas.conversation_schemas import ConversationAppend
        repo = ConversationRepository()
        await repo.append_message_to_history("lead_conv2", "9876543210",
                                             ConversationAppend(role="user", content="Hello"))
        await repo.append_message_to_history("lead_conv2", "9876543210",
                                             ConversationAppend(role="assistant", content="Hi there!"))
        result = await repo.get_conversation_by_lead("lead_conv2")
        assert len(result["messages"]) == 2

    @pytest.mark.asyncio
    async def test_get_conversation_not_found(self, mock_db):
        from apps.api.repositories.conversation_repository import ConversationRepository
        repo = ConversationRepository()
        result = await repo.get_conversation_by_lead("nonexistent_lead")
        assert result is None


class TestWebhookEventRepository:
    """Validates apps/api/repositories/webhook_event_repository.py."""

    @pytest.mark.asyncio
    async def test_insert_raw_event(self, mock_db):
        from apps.api.repositories.webhook_event_repository import WebhookEventRepository
        from apps.api.schemas.webhook_event import WebhookEventCreate
        repo = WebhookEventRepository()
        event = WebhookEventCreate(
            platform="whatsapp",
            event_type="message",
            sender="9876543210",
            payload={"text": "Hello"}
        )
        result = await repo.insert_raw_event(event)
        assert result["event_id"].startswith("evt_")
        assert result["processing_status"] == "pending"

    @pytest.mark.asyncio
    async def test_update_status(self, mock_db):
        from apps.api.repositories.webhook_event_repository import WebhookEventRepository
        from apps.api.schemas.webhook_event import WebhookEventCreate
        repo = WebhookEventRepository()
        event = WebhookEventCreate(
            platform="whatsapp",
            event_type="message",
            sender="9876543210",
            payload={"text": "Test"}
        )
        inserted = await repo.insert_raw_event(event)
        success = await repo.update_status(inserted["event_id"], "processed")
        assert success is True

    @pytest.mark.asyncio
    async def test_log_activity(self, mock_db):
        from apps.api.repositories.webhook_event_repository import WebhookEventRepository
        repo = WebhookEventRepository()
        success = await repo.log_activity(
            lead_id="lead_abc",
            activity_type="message_received",
            metadata={"source": "whatsapp"}
        )
        assert success is True

    @pytest.mark.asyncio
    async def test_create_indexes(self, mock_db):
        from apps.api.repositories.webhook_event_repository import WebhookEventRepository
        repo = WebhookEventRepository()
        await repo.create_indexes()


class TestAnalyticsRepository:
    """Validates apps/api/repositories/analytics_repository.py."""

    @pytest.mark.asyncio
    async def test_get_pipeline_metrics_empty(self, mock_db):
        from apps.api.repositories.analytics_repository import AnalyticsRepository
        repo = AnalyticsRepository()
        metrics = await repo.get_pipeline_metrics()
        assert metrics["total_active_leads"] == 0
        assert metrics["conversion_rate_percentage"] == 0.0
        assert metrics["total_deal_revenue"] == 0

    @pytest.mark.asyncio
    async def test_calculate_hotness_no_lead(self, mock_db):
        from apps.api.repositories.analytics_repository import AnalyticsRepository
        repo = AnalyticsRepository()
        score = await repo.calculate_and_update_hotness("nonexistent_lead")
        assert score == 0


class TestSiteVisitRepository:
    """Validates apps/api/repositories/site_visit_repository.py."""

    @pytest.mark.asyncio
    async def test_insert_site_visit(self, mock_db):
        from apps.api.repositories.site_visit_repository import SiteVisitRepository
        from datetime import datetime, timezone
        repo = SiteVisitRepository()
        scheduled_at = datetime.now(timezone.utc)
        result = await repo.insert_site_visit(
            lead_id="lead_sv1",
            property_id="prop_sv1",
            scheduled_at=scheduled_at,
            notes="Morning visit"
        )
        assert result["lead_id"] == "lead_sv1"
        assert result["property_id"] == "prop_sv1"
        assert result["status"] == "SCHEDULED"
        assert result["notes"] == "Morning visit"
        assert "id" in result

    @pytest.mark.asyncio
    async def test_get_site_visits_by_lead(self, mock_db):
        from apps.api.repositories.site_visit_repository import SiteVisitRepository
        from datetime import datetime, timezone
        import asyncio
        repo = SiteVisitRepository()
        for i in range(3):
            await repo.insert_site_visit(
                lead_id="lead_sv_list",
                property_id=f"prop_{i}",
                scheduled_at=datetime.now(timezone.utc)
            )
            await asyncio.sleep(0.01)
        visits = await repo.get_site_visits_by_lead("lead_sv_list")
        assert len(visits) == 3
        assert visits[0]["property_id"] == "prop_2"

    @pytest.mark.asyncio
    async def test_get_all_active_site_visits(self, mock_db):
        from apps.api.repositories.site_visit_repository import SiteVisitRepository
        from datetime import datetime, timezone
        import asyncio
        repo = SiteVisitRepository()
        t1 = datetime.now(timezone.utc)
        await asyncio.sleep(0.01)
        t2 = datetime.now(timezone.utc)
        await repo.insert_site_visit("lead_1", "prop_1", t2)
        await repo.insert_site_visit("lead_2", "prop_2", t1)
        
        visits = await repo.get_all_active_site_visits()
        assert len(visits) == 2
        assert visits[0]["lead_id"] == "lead_2"
        assert visits[1]["lead_id"] == "lead_1"

    @pytest.mark.asyncio
    async def test_update_site_visit_status(self, mock_db):
        from apps.api.repositories.site_visit_repository import SiteVisitRepository
        from datetime import datetime, timezone
        repo = SiteVisitRepository()
        scheduled_at = datetime.now(timezone.utc)
        visit = await repo.insert_site_visit("lead_sv1", "prop_sv1", scheduled_at)
        
        updated = await repo.update_site_visit_status(visit["id"], "COMPLETED", "Customer loved it")
        assert updated is not None
        assert updated["status"] == "COMPLETED"
        assert updated["notes"] == "Customer loved it"

    @pytest.mark.asyncio
    async def test_create_indexes(self, mock_db):
        from apps.api.repositories.site_visit_repository import SiteVisitRepository
        repo = SiteVisitRepository()
        await repo.create_indexes()
