# tests/test_access_control.py
"""
Locks down who can call what:
  - anonymous callers get 401 on every staff endpoint
  - self-registered client accounts get 403 on every staff endpoint
  - registration can never grant a staff role
"""
import pytest

STAFF_ENDPOINTS = [
    ("get", "/properties/"),
    ("post", "/properties/raw-chunk"),
    ("delete", "/properties/prop_1"),
    ("get", "/leads"),
    ("delete", "/leads/lead_1"),
    ("get", "/leads/queue"),
    ("get", "/conversations/lead_1"),
    ("post", "/matches/trigger/lead_1"),
    ("get", "/matches/lead_1"),
    ("get", "/analytics/pipeline"),
    ("get", "/analytics/lead-summary"),
    ("get", "/operator-actions"),
    ("get", "/site-visits/active"),
    ("get", "/site-visits/lead/lead_1"),
]


@pytest.mark.parametrize("method,path", STAFF_ENDPOINTS)
def test_staff_endpoints_reject_anonymous_callers(anon_client, method, path):
    response = getattr(anon_client, method)(path)
    assert response.status_code == 401


@pytest.mark.parametrize("method,path", STAFF_ENDPOINTS)
def test_staff_endpoints_reject_client_accounts(client_role_client, method, path):
    response = getattr(client_role_client, method)(path)
    assert response.status_code == 403


def test_root_is_public(anon_client):
    assert anon_client.get("/").status_code == 200


def test_registration_always_creates_client_role(anon_client):
    response = anon_client.post("/auth/register", json={
        "email": "attacker@nph.com",
        "password": "securepass123",
        "full_name": "Would-be Admin",
        "role": "admin",
    })
    assert response.status_code == 201
    assert response.json()["role"] == "client"
