# tests/test_api_routes.py
"""
Integration tests for all FastAPI API routes.
Uses the TestClient fixture from conftest.py which wires up all routers
against mock MongoDB collections.
"""
import pytest
from unittest.mock import patch, MagicMock


class TestRootEndpoint:
    """Tests the root health check endpoint."""

    def test_root_returns_message(self, api_client):
        response = api_client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert data["message"] == "NPH Operating System Backend Platform Running"


class TestAuthRoutes:
    """Tests /auth/register and /auth/login endpoints."""

    def test_register_new_user(self, api_client):
        response = api_client.post("/auth/register", json={
            "email": "newuser@nph.com",
            "password": "securepass123",
            "full_name": "New User",
            "role": "broker"
        })
        assert response.status_code == 201
        data = response.json()
        assert data["email"] == "newuser@nph.com"
        assert data["full_name"] == "New User"

    def test_register_duplicate_email_rejected(self, api_client):
        # Register first
        api_client.post("/auth/register", json={
            "email": "duplicate@nph.com",
            "password": "securepass123",
            "full_name": "User One",
        })
        # Attempt duplicate
        response = api_client.post("/auth/register", json={
            "email": "duplicate@nph.com",
            "password": "anotherpass",
            "full_name": "User Two",
        })
        assert response.status_code == 400
        assert "already registered" in response.json()["detail"]

    def test_register_invalid_payload(self, api_client):
        response = api_client.post("/auth/register", json={
            "email": "not-valid-email",
            "password": "ab",  # Too short
            "full_name": "X",  # Too short
        })
        assert response.status_code == 422

    def test_login_success(self, api_client):
        # Register first
        api_client.post("/auth/register", json={
            "email": "logintest@nph.com",
            "password": "mypassword",
            "full_name": "Login User",
        })
        # Login
        response = api_client.post("/auth/login", data={
            "username": "logintest@nph.com",
            "password": "mypassword",
        })
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"

    def test_login_wrong_password(self, api_client):
        api_client.post("/auth/register", json={
            "email": "wrongpw@nph.com",
            "password": "correctpassword",
            "full_name": "Test User",
        })
        response = api_client.post("/auth/login", data={
            "username": "wrongpw@nph.com",
            "password": "wrongpassword",
        })
        assert response.status_code == 401

    def test_login_nonexistent_user(self, api_client):
        response = api_client.post("/auth/login", data={
            "username": "ghost@nph.com",
            "password": "anypassword",
        })
        assert response.status_code == 401


class TestLeadRoutes:
    """Tests /leads CRUD endpoints."""

    def _create_lead_payload(self, name="Test Lead", phone="9876543210"):
        return {
            "id": phone,
            "name": name,
            "status": "DISCOVERY",
            "requirements": {
                "city": "Nashik",
                "area": "Indira Nagar",
                "bhk": 2,
                "min_price": 8000.0,
                "max_price": 15000.0,
                "property_type": "apartment",
                "listing_type": "rent"
            }
        }

    def test_create_lead(self, api_client):
        response = api_client.post("/leads", json=self._create_lead_payload())
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "Test Lead"
        assert data["id"] == "9876543210"
        assert data["status"] == "DISCOVERY"

    def test_list_leads(self, api_client):
        api_client.post("/leads", json=self._create_lead_payload("Lead A", "9876543211"))
        api_client.post("/leads", json=self._create_lead_payload("Lead B", "9876543212"))
        response = api_client.get("/leads")
        assert response.status_code == 200
        data = response.json()
        assert len(data) >= 2

    def test_get_lead_by_id(self, api_client):
        create_resp = api_client.post("/leads", json=self._create_lead_payload())
        lead_id = create_resp.json()["id"]
        response = api_client.get(f"/leads/{lead_id}")
        assert response.status_code == 200
        assert response.json()["id"] == lead_id

    def test_get_lead_not_found(self, api_client):
        response = api_client.get("/leads/lead_nonexistent")
        assert response.status_code == 404

    def test_update_lead(self, api_client):
        create_resp = api_client.post("/leads", json=self._create_lead_payload())
        lead_id = create_resp.json()["id"]
        response = api_client.patch(f"/leads/{lead_id}", json={"name": "Updated Name"})
        assert response.status_code == 200
        assert response.json()["name"] == "Updated Name"

    def test_delete_lead(self, api_client):
        create_resp = api_client.post("/leads", json=self._create_lead_payload())
        lead_id = create_resp.json()["id"]
        response = api_client.delete(f"/leads/{lead_id}")
        assert response.status_code == 204

    def test_delete_nonexistent_lead(self, api_client):
        response = api_client.delete("/leads/lead_fake")
        assert response.status_code == 404

    def test_create_lead_invalid_payload(self, api_client):
        response = api_client.post("/leads", json={
            "name": "X",
            "email": "invalid-email"
        })
        assert response.status_code == 422


class TestConversationRoutes:
    """Tests /conversations endpoints."""

    def test_append_and_get_conversation(self, api_client):
        # First create a lead
        lead_resp = api_client.post("/leads", json={
            "id": "9876543210",
            "name": "Conv Lead",
            "status": "DISCOVERY",
            "requirements": {
                "city": "Nashik",
                "area": "Area",
                "bhk": 2,
                "min_price": 5000.0,
                "max_price": 10000.0,
                "property_type": "apartment",
                "listing_type": "rent"
            }
        })
        lead_id = lead_resp.json()["id"]

        # Append a message
        response = api_client.post(f"/conversations/{lead_id}", json={
            "role": "user",
            "content": "I need 2BHK flat near college road"
        })
        assert response.status_code == 200
        data = response.json()
        assert data["lead_id"] == lead_id
        assert len(data["messages"]) >= 1

    def test_append_to_nonexistent_lead(self, api_client):
        response = api_client.post("/conversations/lead_ghost", json={
            "role": "user",
            "content": "Hello"
        })
        assert response.status_code == 404

    def test_get_conversation_not_found(self, api_client):
        response = api_client.get("/conversations/lead_nonexistent")
        assert response.status_code == 404



class TestSystemRoutes:
    """Tests /system endpoints."""

    def test_health_check(self, api_client, mock_redis):
        response = api_client.get("/system/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["infrastructure"]["redis_cache"] == "connected"
        assert data["infrastructure"]["mongodb_atlas"] == "connected"

    def test_health_check_redis_down(self, api_client):
        with patch("apps.api.routers.system.redis_client") as mock_r:
            mock_r.ping.side_effect = ConnectionError("Redis down")
            response = api_client.get("/system/health")
            assert response.status_code == 503

    @patch("apps.api.routers.system.celery_client")
    def test_trigger_analytics(self, mock_celery, api_client):
        mock_task = MagicMock()
        mock_task.id = "test_task_id_123"
        mock_celery.send_task.return_value = mock_task

        response = api_client.post("/system/trigger-analytics", json={
            "locality": "Indira Nagar"
        })
        assert response.status_code == 202
        data = response.json()
        assert data["status"] == "queued"
        assert data["target_locality"] == "Indira Nagar"


class TestAnalyticsRoutes:
    """Tests /analytics endpoints."""

    def test_pipeline_dashboard(self, api_client):
        response = api_client.get("/analytics/pipeline")
        assert response.status_code == 200
        data = response.json()
        assert "total_active_leads" in data
        assert "hot_leads_count" in data
        assert "conversion_rate_percentage" in data

    def test_followup_nonexistent_lead(self, api_client):
        response = api_client.post("/analytics/followup/lead_fake")
        assert response.status_code == 404





class TestWebhookRoutes:
    """Tests /webhooks endpoints."""

    def test_meta_verification_handshake(self, api_client):
        response = api_client.get("/webhooks/whatsapp", params={
            "hub.mode": "subscribe",
            "hub.challenge": "test_challenge_123",
            "hub.verify_token": "<redacted-verify-token>"
        })
        assert response.status_code == 200
        assert response.text == "test_challenge_123"

    def test_meta_verification_bad_token(self, api_client):
        response = api_client.get("/webhooks/whatsapp", params={
            "hub.mode": "subscribe",
            "hub.challenge": "test_challenge",
            "hub.verify_token": "wrong_token"
        })
        assert response.status_code == 403

    @patch("apps.api.routes.webhooks.process_incoming_message_event")
    def test_whatsapp_message_ingestion(self, mock_celery_task, api_client):
        mock_celery_task.delay = MagicMock()
        payload = {
            "object": "whatsapp_business_account",
            "entry": [{
                "changes": [{
                    "value": {
                        "messages": [{
                            "from": "919876543210",
                            "type": "text",
                            "text": {"body": "I need 2BHK near college road for 15k"}
                        }]
                    }
                }]
            }]
        }
        response = api_client.post("/webhooks/whatsapp", json=payload)
        assert response.status_code == 202
        assert response.json()["status"] == "accepted"
        mock_celery_task.delay.assert_called_once()

    def test_whatsapp_empty_payload_accepted(self, api_client):
        """Meta sends various non-message payloads; we must always return 2xx."""
        response = api_client.post("/webhooks/whatsapp", json={
            "object": "whatsapp_business_account",
            "entry": []
        })
        assert response.status_code == 202


class TestSearchRoutes:
    """Tests /properties/search endpoint."""

    @pytest.fixture(autouse=True)
    def setup_auth_override(self, api_client):
        from shared.utils.auth_guard import get_current_user
        api_client.app.dependency_overrides[get_current_user] = lambda: {
            "id": "test_user_id_123",
            "email": "test@nph.com",
            "role": "admin"
        }
        yield
        api_client.app.dependency_overrides.clear()

    def test_search_empty_results(self, api_client):
        response = api_client.get("/properties/search", params={
            "area": "NonexistentLocality",
            "bhk": 3,
            "listing_type": "rent"
        })
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 0

    def test_search_with_filters(self, api_client):
        response = api_client.get("/properties/search", params={
            "bhk": 2,
            "area": "Indira Nagar",
            "listing_type": "rent",
            "max_price": 20000,
        })
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
