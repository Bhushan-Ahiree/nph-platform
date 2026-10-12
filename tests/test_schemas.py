# tests/test_schemas.py
"""
Tests for all Pydantic schema models across the project.
Validates field constraints, defaults, serialization, and rejection of invalid data.
"""
import pytest
from datetime import datetime, timezone
from pydantic import ValidationError


# ============================================================================
# Shared Schemas
# ============================================================================

class TestUserSchemas:
    """Validates shared/schemas/user.py models."""

    def test_user_register_valid(self):
        from shared.schemas.user import UserRegister
        user = UserRegister(
            email="broker@nph.com",
            password="securepass123",
            full_name="Bhushan Ahiree",
            role="broker"
        )
        assert user.email == "broker@nph.com"
        assert user.full_name == "Bhushan Ahiree"
        assert user.role == "broker"

    def test_user_register_default_role(self):
        from shared.schemas.user import UserRegister
        user = UserRegister(
            email="test@nph.com",
            password="securepass123",
            full_name="Test User"
        )
        assert user.role == "broker"

    def test_user_register_short_password_rejected(self):
        from shared.schemas.user import UserRegister
        with pytest.raises(ValidationError):
            UserRegister(
                email="test@nph.com",
                password="abc",  # Too short (min 6)
                full_name="Test User"
            )

    def test_user_register_invalid_email_rejected(self):
        from shared.schemas.user import UserRegister
        with pytest.raises(ValidationError):
            UserRegister(
                email="not-an-email",
                password="securepass123",
                full_name="Test User"
            )

    def test_user_register_short_name_rejected(self):
        from shared.schemas.user import UserRegister
        with pytest.raises(ValidationError):
            UserRegister(
                email="test@nph.com",
                password="securepass123",
                full_name="X"  # Too short (min 2)
            )

    def test_user_login_valid(self):
        from shared.schemas.user import UserLogin
        login = UserLogin(email="test@nph.com", password="pass123")
        assert login.email == "test@nph.com"

    def test_token_model(self):
        from shared.schemas.user import Token
        token = Token(access_token="abc123", token_type="bearer")
        assert token.access_token == "abc123"
        assert token.token_type == "bearer"


class TestPropertySchemas:
    """Validates shared/schemas/property.py models."""

    def test_property_create_valid(self):
        from apps.api.schemas.property_schema_v2 import PropertyCreate
        prop = PropertyCreate(
            title="2 BHK Apartment in Indira Nagar",
            area="Indira Nagar",
            price=15000,
            bhk=2
        )
        assert prop.title == "2 BHK Apartment in Indira Nagar"
        assert prop.city == "Nashik"  # default
        assert prop.property_type == "apartment"  # default
        assert prop.listing_type == "rent"  # default
        assert prop.parking is False

    def test_property_create_defaults(self):
        from apps.api.schemas.property_schema_v2 import PropertyCreate
        prop = PropertyCreate(title="Test", area="Test Area", price=10000)
        assert prop.source.type == "broker_group"
        assert prop.availability.status == "active"
        assert prop.rental_details.deposit == 0
        assert prop.intelligence.hot_property is False
        assert prop.intelligence.duplicate_count == 0
        assert prop.intelligence.source_confidence == 100

    def test_property_source_defaults(self):
        from apps.api.schemas.property_schema_v2 import PropertySource
        source = PropertySource()
        assert source.type == "broker_group"
        assert source.group_name is None
        assert source.broker_name is None

    def test_property_availability_defaults(self):
        from apps.api.schemas.property_schema_v2 import PropertyAvailability
        avail = PropertyAvailability()
        assert avail.status == "active"
        assert avail.verified_by == "automated"

    def test_property_rental_details_defaults(self):
        from apps.api.schemas.property_schema_v2 import PropertyRentalDetails
        rental = PropertyRentalDetails()
        assert rental.deposit == 0
        assert rental.preferred_tenant == "any"
        assert rental.furnishing == "unfurnished"

    def test_property_create_missing_required_field(self):
        from apps.api.schemas.property_schema_v2 import PropertyCreate
        with pytest.raises(ValidationError):
            PropertyCreate(title="Test", area="Test Area")  # missing price

    def test_property_legacy_compatibility(self):
        from apps.api.schemas.property_schema_v2 import PropertyDB
        from datetime import datetime
        legacy_data = {
            "_id": "6a10781883d1ddbe5fa40011",
            "title": "Cozy 1 BHK Flat in Wakad Pune",
            "property_type": "Apartment",
            "listing_type": "Sale",
            "price": 3200000.0,
            "maintenance_monthly": 0.0,
            "deposit_amount": 0.0,
            "carpet_area_sqft": 520.0,
            "super_area_sqft": None,
            "construction_status": "Ready to Move",
            "possession_date": None,
            "rera_id": None,
            "furnishing_status": "Unfurnished",
            "parking_covered": 0,
            "parking_open": 0,
            "facing": None,
            "location": {"city": "Nashik", "locality": "Wakad", "coordinates": None},
            "contact": {"name": "NPH Ingestion Bot", "phone": "+919999999999", "type": "Agent"},
            "features": [],
            "amenities": [],
            "images": [],
            "status": "active",
            "property_id": "prop_774d8865",
            "created_at": datetime(2026, 5, 22, 15, 36, 56, 133000),
            "updated_at": datetime(2026, 5, 22, 15, 36, 56, 133000)
        }
        prop = PropertyDB(**legacy_data)
        assert prop.area == "Wakad"
        assert prop.city == "Nashik"
        assert prop.bhk == 1
        assert prop.parking is False
        assert prop.source.broker_name == "NPH Ingestion Bot"
        assert prop.rental_details.deposit == 0
        assert prop.rental_details.furnishing == "unfurnished"
        assert prop.availability.status == "active"



# ============================================================================
# API Schemas
# ============================================================================

class TestLeadSchemas:
    """Validates apps/api/schemas/lead_schemas.py models."""

    def test_lead_create_valid(self):
        from apps.api.schemas.lead_schemas import LeadCreate
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
        assert lead.name == "Rahul Sharma"
        assert lead.id == "9876543210"
        assert lead.requirements.bhk == 2
        assert lead.status == "DISCOVERY"

    def test_lead_create_empty_requirements(self):
        from apps.api.schemas.lead_schemas import LeadCreate
        lead = LeadCreate(id="9876543210")
        assert lead.id == "9876543210"
        assert lead.status == "DISCOVERY"
        assert lead.requirements.bhk is None
        assert lead.requirements.area is None

    def test_lead_update_partial(self):
        from apps.api.schemas.lead_schemas import LeadUpdate
        update = LeadUpdate(name="Updated Name")
        dump = update.model_dump(exclude_unset=True)
        assert dump == {"name": "Updated Name"}

    def test_lead_response_defaults(self):
        from apps.api.schemas.lead_schemas import LeadResponse
        response = LeadResponse(
            id="9876543210",
            status="DISCOVERY",
            requirements={
                "city": "Nashik",
                "area": "Indira Nagar",
                "bhk": 2,
                "min_price": 8000,
                "max_price": 15000,
                "property_type": "apartment",
                "listing_type": "rent"
            },
            name="Test",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        assert response.status == "DISCOVERY"



class TestWebhookEventSchemas:
    """Validates apps/api/schemas/webhook_event.py models."""

    def test_webhook_event_create_valid(self):
        from apps.api.schemas.webhook_event import WebhookEventCreate
        event = WebhookEventCreate(
            platform="whatsapp",
            event_type="message",
            sender="9876543210",
            payload={"text": "I need 2bhk in Indira Nagar"}
        )
        assert event.platform == "whatsapp"
        assert event.sender == "9876543210"

    def test_webhook_event_invalid_platform(self):
        from apps.api.schemas.webhook_event import WebhookEventCreate
        with pytest.raises(ValidationError):
            WebhookEventCreate(
                platform="telegram",  # Not whatsapp or instagram
                event_type="message",
                sender="9876543210",
                payload={"text": "hello"}
            )

    def test_webhook_event_invalid_sender(self):
        from apps.api.schemas.webhook_event import WebhookEventCreate
        with pytest.raises(ValidationError):
            WebhookEventCreate(
                platform="whatsapp",
                sender="abc",  # Not numeric
                payload={"text": "hello"}
            )


class TestMatchSchemas:
    """Validates apps/api/schemas/match_schemas.py models."""

    def test_match_response_valid(self):
        from apps.api.schemas.match_schemas import MatchResponse
        match = MatchResponse(
            match_id="match_abc123",
            lead_id="lead_xyz",
            property_ids=["prop_abc", "prop_123"],
            status="SENT",
            generated_at=datetime.now(timezone.utc)
        )
        assert match.id == "match_abc123"
        assert match.lead_id == "lead_xyz"
        assert match.property_ids == ["prop_abc", "prop_123"]
        assert match.status == "SENT"

    def test_match_create_valid(self):
        from apps.api.schemas.match_schemas import MatchCreate
        match = MatchCreate(
            lead_id="lead_xyz",
            property_ids=["prop_abc"],
            status="SENT"
        )
        assert match.lead_id == "lead_xyz"
        assert match.property_ids == ["prop_abc"]
        assert match.status == "SENT"

    def test_match_update_valid(self):
        from apps.api.schemas.match_schemas import MatchUpdate
        update = MatchUpdate(status="VIEWED")
        assert update.status == "VIEWED"


class TestConversationSchemas:
    """Validates apps/api/schemas/conversation_schemas.py models."""

    def test_conversation_append_valid(self):
        from apps.api.schemas.conversation_schemas import ConversationAppend
        msg = ConversationAppend(role="user", content="I want 2BHK flat")
        assert msg.role == "user"
        assert msg.content == "I want 2BHK flat"

    def test_conversation_append_invalid_role(self):
        from apps.api.schemas.conversation_schemas import ConversationAppend
        with pytest.raises(ValidationError):
            ConversationAppend(role="moderator", content="hello")

    def test_message_block_timestamp_auto(self):
        from apps.api.schemas.conversation_schemas import MessageBlock
        block = MessageBlock(role="assistant", content="Here are your options")
        assert block.timestamp is not None


class TestSiteVisitSchemas:
    """Validates apps/api/schemas/site_visit_schemas.py models."""

    def test_site_visit_create_valid(self):
        from apps.api.schemas.site_visit_schemas import SiteVisitCreate
        from datetime import datetime, timezone
        visit = SiteVisitCreate(
            lead_id="lead_abc",
            property_id="prop_xyz",
            scheduled_at=datetime.now(timezone.utc),
            notes="Requires morning viewing"
        )
        assert visit.lead_id == "lead_abc"
        assert visit.property_id == "prop_xyz"
        assert visit.notes == "Requires morning viewing"

    def test_site_visit_update_partial(self):
        from apps.api.schemas.site_visit_schemas import SiteVisitUpdate, VisitStatus
        update = SiteVisitUpdate(status=VisitStatus.COMPLETED, notes="Shown flat successfully")
        assert update.status == VisitStatus.COMPLETED
        assert update.notes == "Shown flat successfully"

    def test_visit_status_enum_values(self):
        from apps.api.schemas.site_visit_schemas import VisitStatus
        assert VisitStatus.SCHEDULED == "SCHEDULED"
        assert VisitStatus.COMPLETED == "COMPLETED"
        assert VisitStatus.CANCELLED == "CANCELLED"
        assert VisitStatus.NOSHOW == "NOSHOW"


class TestPropertySchemaV2:
    """Validates apps/api/schemas/property_schema_v2.py models."""

    def test_property_v2_valid(self):
        from apps.api.schemas.property_schema_v2 import PropertySchemaV2
        prop = PropertySchemaV2(
            title="3 BHK Villa in Gangapur Road",
            area="Gangapur Road",
            price=25000,
            bhk=3,
            source={"type": "broker_group"}
        )
        assert prop.property_type == "apartment"
        assert prop.listing_type == "rent"
        assert prop.city == "Nashik"
        assert prop.parking is False
        assert prop.availability.status == "active"

    def test_property_v2_invalid_city(self):
        from apps.api.schemas.property_schema_v2 import PropertySchemaV2
        with pytest.raises(ValidationError):
            PropertySchemaV2(
                title="Test",
                area="Test",
                price=10000,
                city="Delhi",  # Not in Literal
                source={"type": "broker_group"}
            )

    def test_property_v2_invalid_listing_type(self):
        from apps.api.schemas.property_schema_v2 import PropertySchemaV2
        with pytest.raises(ValidationError):
            PropertySchemaV2(
                title="Test",
                area="Test",
                price=10000,
                listing_type="exchange",  # Not in Literal
                source={"type": "broker_group"}
            )

    def test_property_v2_timestamps_auto(self):
        from apps.api.schemas.property_schema_v2 import PropertySchemaV2
        prop = PropertySchemaV2(
            title="Test",
            area="Test",
            price=10000,
            source={"type": "broker_group"}
        )
        assert prop.created_at is not None
        assert prop.updated_at is not None


class TestAnalyticsSchemas:
    """Validates apps/api/schemas/analytics_schemas.py models."""

    def test_pipeline_summary_response(self):
        from apps.api.schemas.analytics_schemas import PipelineSummaryResponse
        summary = PipelineSummaryResponse(
            total_active_leads=50,
            hot_leads_count=10,
            warm_leads_count=20,
            cold_leads_count=20,
            site_visits_booked=5,
            site_visits_paid=3,
            conversion_rate_percentage=6.0,
            total_deal_revenue=150000.0
        )
        assert summary.total_active_leads == 50
        assert summary.conversion_rate_percentage == 6.0

    def test_task_trigger_schema(self):
        from apps.api.schemas.task_schemas import AnalyticsTaskTrigger
        trigger = AnalyticsTaskTrigger(locality="Indira Nagar")
        assert trigger.locality == "Indira Nagar"


class TestSharedAnalyticsSchemas:
    """Validates shared/schemas/analytics_schemas.py models."""

    def test_locality_snapshot_valid(self):
        from shared.schemas.analytics_schemas import LocalitySnapshot
        snap = LocalitySnapshot(
            locality="Indira Nagar",
            city="Nashik",
            average_price_sqft=4500.0,
            total_active_listings=25,
            market_velocity="High"
        )
        assert snap.locality == "Indira Nagar"
        assert snap.last_updated is not None
