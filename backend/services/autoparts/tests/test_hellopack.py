from __future__ import annotations

from app.hellopack import HelloPackService
from app.hellopack.service import HelloPackService as HelloPackServiceDirect


def test_hellopack_service_greets_known_company(db_session, demo_company_id):
    assert HelloPackService(db_session).greet(demo_company_id).startswith("Hello,")


def test_hellopack_service_greets_unknown(db_session):
    import uuid

    unknown = uuid.uuid4()
    assert HelloPackServiceDirect(db_session).greet(unknown) == "Hello, unknown company!"


def test_hellopack_endpoint(client):
    response = client.get("/api/v1/hellopack/hello")
    assert response.status_code == 200
    assert response.json()["message"].startswith("Hello,")


def test_internal_metrics_requires_token(client):
    response = client.get("/internal/metrics")
    assert response.status_code == 401


def test_internal_metrics_shape(client):
    from shared.internal import internal_token

    response = client.get(
        "/internal/metrics",
        headers={"X-Internal-Token": internal_token()},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["namespace"] == "autoparts"
    assert "suppliers" in payload["metrics"]
    assert "attempts_total" in payload["metrics"]["suppliers"]
    assert "success_rate" in payload["metrics"]["suppliers"]
    assert "orders" in payload["metrics"]
    assert "revenue" in payload["metrics"]
