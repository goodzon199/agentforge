from __future__ import annotations

def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_dashboard(client):
    resp = client.get("/api/v1/dashboard")
    assert resp.status_code == 200
    data = resp.json()
    assert data["companies"] == 1
    assert data["agents"] == 1


def test_create_and_run_task_via_api(client):
    companies = client.get("/api/v1/companies").json()
    company_id = companies[0]["id"]

    resp = client.post(
        "/api/v1/tasks",
        json={
            "company_id": company_id,
            "title": "Найти тормозные колодки",
            "objective": "Найди тормозные колодки",
            "priority": "normal",
        },
    )
    assert resp.status_code == 201
    task = resp.json()
    assert task["status"] == "completed"
    assert task["routing_decision"]["needs_agent"] == "SearchAgent"
    assert len(task["events"]) >= 2


def test_create_company(client):
    resp = client.post(
        "/api/v1/companies",
        json={"name": "ООО Тест", "slug": "test-llc", "description": "", "agent_quota": 5},
    )
    assert resp.status_code == 201
    assert resp.json()["slug"] == "test-llc"


def test_tools_endpoint(client):
    resp = client.get("/api/v1/settings/tools")
    assert resp.status_code == 200
    names = {t["name"] for t in resp.json()}
    assert "search" in names
    assert "email" in names
