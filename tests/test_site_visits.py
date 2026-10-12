# tests/test_site_visits.py
import pytest
from datetime import datetime, timezone


class TestSiteVisitRoutes:
    """Validates the /site-visits router endpoints and business side-effects."""

    def test_create_site_visit_success(self, api_client, mock_db):
        # Insert a lead to avoid constraint issues if lead checks exist (optional but robust)
        scheduled_time = datetime.now(timezone.utc).isoformat()
        response = api_client.post("/site-visits/", json={
            "lead_id": "9876543210",
            "property_id": "prop_visit_xyz",
            "scheduled_at": scheduled_time,
            "notes": "First viewing of the flat"
        })
        assert response.status_code == 201
        data = response.json()
        assert data["lead_id"] == "9876543210"
        assert data["property_id"] == "prop_visit_xyz"
        assert data["status"] == "SCHEDULED"
        assert data["notes"] == "First viewing of the flat"
        assert "id" in data
        assert "created_at" in data

    def test_get_lead_visits(self, api_client, mock_db):
        scheduled_time = datetime.now(timezone.utc).isoformat()
        # Create a visit
        api_client.post("/site-visits/", json={
            "lead_id": "9876543211",
            "property_id": "prop_visit_1",
            "scheduled_at": scheduled_time
        })
        # Create another visit for same lead
        api_client.post("/site-visits/", json={
            "lead_id": "9876543211",
            "property_id": "prop_visit_2",
            "scheduled_at": scheduled_time
        })

        response = api_client.get("/site-visits/lead/9876543211")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2

    def test_get_active_site_visits(self, api_client, mock_db):
        # Ensure we only fetch SCHEDULED status
        scheduled_time = datetime.now(timezone.utc).isoformat()
        # Insert a SCHEDULED visit
        response_create = api_client.post("/site-visits/", json={
            "lead_id": "9876543212",
            "property_id": "prop_active",
            "scheduled_at": scheduled_time
        })
        visit_id = response_create.json()["id"]

        # Insert a visit and then update to completed
        response_completed = api_client.post("/site-visits/", json={
            "lead_id": "9876543213",
            "property_id": "prop_completed",
            "scheduled_at": scheduled_time
        })
        comp_id = response_completed.json()["id"]
        api_client.patch(f"/site-visits/{comp_id}", json={"status": "COMPLETED"})

        # Get active visits
        response_active = api_client.get("/site-visits/active")
        assert response_active.status_code == 200
        active_list = response_active.json()
        
        # Should contain the SCHEDULED visit but not the COMPLETED one
        assert any(v["id"] == visit_id for v in active_list)
        assert not any(v["id"] == comp_id for v in active_list)

    @pytest.mark.asyncio
    async def test_patch_site_visit_updates_lead_status(self, api_client, mock_db):
        # 1. Create a lead in the database
        from apps.api.repositories.lead_repository import LeadRepository
        from apps.api.schemas.lead_schemas import LeadCreate
        lead_repo = LeadRepository()
        
        lead_id = "9112233445"
        await lead_repo.insert_lead(LeadCreate(id=lead_id))
        
        # 2. Schedule a site visit for this lead
        scheduled_time = datetime.now(timezone.utc).isoformat()
        response_create = api_client.post("/site-visits/", json={
            "lead_id": lead_id,
            "property_id": "prop_patch_test",
            "scheduled_at": scheduled_time
        })
        visit_data = response_create.json()
        visit_id = visit_data["id"]

        # Lead status starts at DISCOVERY
        lead_before = await lead_repo.get_lead_by_id(lead_id)
        assert lead_before["status"] == "DISCOVERY"

        # 3. Patch the visit to SCHEDULED (should update lead status to VISIT_SCHEDULED)
        patch_response_1 = api_client.patch(f"/site-visits/{visit_id}", json={
            "status": "SCHEDULED",
            "notes": "Time confirmed with client"
        })
        assert patch_response_1.status_code == 200
        assert patch_response_1.json()["status"] == "SCHEDULED"
        assert patch_response_1.json()["notes"] == "Time confirmed with client"

        lead_scheduled = await lead_repo.get_lead_by_id(lead_id)
        assert lead_scheduled["status"] == "VISIT_SCHEDULED"

        # 4. Patch the visit to COMPLETED (should update lead status to VISIT_COMPLETED)
        patch_response_2 = api_client.patch(f"/site-visits/{visit_id}", json={
            "status": "COMPLETED",
            "notes": "Shown property successfully"
        })
        assert patch_response_2.status_code == 200
        assert patch_response_2.json()["status"] == "COMPLETED"
        assert patch_response_2.json()["notes"] == "Shown property successfully"

        lead_completed = await lead_repo.get_lead_by_id(lead_id)
        assert lead_completed["status"] == "VISIT_COMPLETED"
