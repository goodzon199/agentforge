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
