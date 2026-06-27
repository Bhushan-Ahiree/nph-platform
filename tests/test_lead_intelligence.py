# tests/test_lead_intelligence.py
import pytest
from services.lead.scoring import calculate_priority_score, calculate_temperature
from apps.worker.tasks.webhook_tasks import detect_owner_confidence

def test_scoring_logic():
    # Cold lead (no requirements)
    lead_cold = {
        "lead_type": "CLIENT",
        "requirements": {}
    }
    score_cold = calculate_priority_score(lead_cold)
    assert score_cold == 15
    assert calculate_temperature(score_cold) == "COLD"

    # Hot lead (complete requirements)
    lead_hot = {
        "lead_type": "CLIENT",
        "requirements": {
            "area": "Wakad",
            "bhk": 2,
            "listing_type": "rent",
            "max_price": 20000
        }
    }
    score_hot = calculate_priority_score(lead_hot)
    # 25 (complete) + 15 (budget) + 15 (area) + 15 (bhk) + 15 (client) = 85
    assert score_hot == 85
    assert calculate_temperature(score_hot) == "HOT"

def test_owner_detection():
    assert detect_owner_confidence("I am the owner of this flat") == 0.8
    assert detect_owner_confidence("direct owner here") == 0.8
    assert detect_owner_confidence("looking for a 2bhk") == 0.0

@pytest.mark.asyncio
async def test_analytics_lead_summary(api_client, auth_token, mock_db):
    for doc in [
        {"lead_id": "l1", "lead_temperature": "HOT", "lead_type": "CLIENT", "source": "whatsapp"},
        {"lead_id": "l2", "lead_temperature": "WARM", "lead_type": "BROKER", "source": "instagram"},
    ]:
        mock_db.client.nph_core.leads.insert_one(doc)
    
    response = api_client.get(
        "/analytics/lead-summary",
        headers={"Authorization": f"Bearer {auth_token}"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total_leads"] == 2
    assert data["hot_leads"] == 1
    assert data["warm_leads"] == 1
    assert data["whatsapp"] == 1

@pytest.mark.asyncio
async def test_operator_actions_queue(api_client, auth_token, mock_db):
    from datetime import datetime, timezone
    
    mock_db.client.nph_core.operator_actions.insert_one({
        "action_type": "CONFIRM_OWNER",
        "lead_id": "lead_123",
        "status": "PENDING",
        "created_at": datetime.now(timezone.utc)
    })
    
    response = api_client.get(
        "/operator-actions?status=PENDING",
        headers={"Authorization": f"Bearer {auth_token}"}
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["action_type"] == "CONFIRM_OWNER"
    
    action_id = data[0]["id"]
    patch_resp = api_client.patch(
        f"/operator-actions/{action_id}",
        json={"status": "COMPLETED"},
        headers={"Authorization": f"Bearer {auth_token}"}
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["status"] == "COMPLETED"

@pytest.mark.asyncio
async def test_lead_queue(api_client, auth_token, mock_db):
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    for doc in [
        {"lead_id": "q1", "lead_temperature": "HOT", "priority_score": 90, "created_at": now},
        {"lead_id": "q2", "lead_temperature": "WARM", "priority_score": 60, "created_at": now},
    ]:
        mock_db.client.nph_core.leads.insert_one(doc)
    
    response = api_client.get(
        "/leads/queue",
        headers={"Authorization": f"Bearer {auth_token}"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 2
    assert len(data["hot"]) == 1
    assert len(data["warm"]) == 1
    assert data["hot"][0]["priority_score"] == 90
