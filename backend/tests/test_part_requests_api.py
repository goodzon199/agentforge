from __future__ import annotations


def _make_conversation(client, db_session) -> str:
    customer = client.post(
        "/api/v1/customers",
        json={"company_id": str(_company_id(db_session)), "name": "Иван Петров"},
    ).json()["id"]
    return client.post(
        "/api/v1/conversations",
        json={"company_id": str(_company_id(db_session)), "customer_id": customer},
    ).json()["id"]


def _company_id(db_session):
    from sqlalchemy import select

    from app.models import Company

    return db_session.scalars(select(Company)).first().id


def test_list_part_requests_empty(client, db_session):
    resp = client.get("/api/v1/part_requests")
    assert resp.status_code == 200
    assert resp.json() == []


def test_full_flow_dod(client, db_session):
    """Definition of Done: dialog -> part request -> VIN -> ready -> search task."""
    conversation_id = _make_conversation(client, db_session)

    # 1. Client asks for brake pads for a BMW X5 2019.
    first = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"sender_type": "customer", "content": "Нужны передние колодки на BMW X5 2019"},
    )
    assert first.status_code == 201

    # 2. A PartRequest is created and the agent asks for the VIN.
    requests = client.get(
        f"/api/v1/part_requests?conversation_id={conversation_id}"
    ).json()
    assert len(requests) == 1
    part_request = requests[0]
    assert part_request["status"] == "collecting_data"
    assert part_request["part_name"] == "передние тормозные колодки"
    assert part_request["quantity"] == 1
    assert part_request["vehicle"]["brand"] == "BMW"
    assert part_request["vehicle"]["model"] == "X5"
    assert part_request["vehicle"]["year"] == 2019
    assert part_request["missing_fields"] == ["vin"]

    detail = client.get(f"/api/v1/conversations/{conversation_id}").json()
    agent_replies = [m for m in detail["messages"] if m["sender_type"] == "agent"]
    assert len(agent_replies) == 1
    assert "VIN" in agent_replies[0]["content"]

    # 3. Client sends the VIN.
    second = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"sender_type": "customer", "content": "Вот VIN WBAKS410900H12345"},
    )
    assert second.status_code == 201

    # 4. The same PartRequest is updated, auto-searched and now has offers.
    requests = client.get(
        f"/api/v1/part_requests?conversation_id={conversation_id}"
    ).json()
    assert len(requests) == 1  # updated, not duplicated
    part_request = requests[0]
    assert part_request["status"] == "quoted"
    assert part_request["vehicle"]["vin"] == "WBAKS410900H12345"
    assert part_request["missing_fields"] == []

    # 5. A search_parts task was created and completed with offers.
    tasks = client.get("/api/v1/tasks").json()
    search_tasks = [
        t
        for t in tasks
        if t["objective"] == "search_parts"
        and t["input_data"].get("part_request_id") == part_request["id"]
    ]
    assert len(search_tasks) == 1
    assert search_tasks[0]["status"] == "completed"
    assert search_tasks[0]["output_data"]["data"]["offers_found"] == 2
    assert (
        search_tasks[0]["output_data"]["data"]["next_action"] == "pricing_parts"
    )

    # 6. Offers are persisted and visible via the offers endpoint.
    offers = client.get(f"/api/v1/part_requests/{part_request['id']}/offers").json()
    assert len(offers) == 2
    assert {o["article"] for o in offers} == {"P06089", "GDB2119"}

    # 7. The pricing_parts hand-off task was created and completed inline.
    pricing_tasks = [
        t
        for t in tasks
        if t["objective"] == "pricing_parts"
        and t["input_data"].get("part_request_id") == part_request["id"]
    ]
    assert len(pricing_tasks) == 1
    assert pricing_tasks[0]["status"] == "completed"
    assert pricing_tasks[0]["output_data"]["data"]["action"] == "pricing_parts"
    assert pricing_tasks[0]["output_data"]["data"]["best_article"] == "GDB2119"
    assert pricing_tasks[0]["output_data"]["data"]["best_total_price"] == "7930.00"

    # 8. Offers carry the customer-facing price and the quote is available.
    offers = client.get(f"/api/v1/part_requests/{part_request['id']}/offers").json()
    priced = [o for o in offers if o["customer_price"] is not None]
    assert len(priced) == 2
    quote = client.get(f"/api/v1/part_requests/{part_request['id']}/quote").json()
    assert quote["status"] == "priced"
    assert quote["best_article"] == "GDB2119"
    assert quote["best_total_price"] == "7930.00"


def test_reprocessing_message_does_not_duplicate(client, db_session):
    conversation_id = _make_conversation(client, db_session)

    payload = {
        "sender_type": "customer",
        "content": "Нужны колодки на BMW X5 2019",
    }
    first = client.post(f"/api/v1/conversations/{conversation_id}/messages", json=payload)
    assert first.status_code == 201

    # The same message re-sent must not create a second PartRequest.
    second = client.post(f"/api/v1/conversations/{conversation_id}/messages", json=payload)
    assert second.status_code == 201

    requests = client.get(
        f"/api/v1/part_requests?conversation_id={conversation_id}"
    ).json()
    assert len(requests) == 1


def test_filter_by_conversation(client, db_session):
    conversation_id = _make_conversation(client, db_session)
    client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"sender_type": "customer", "content": "Нужны колодки на Kia Rio 2017"},
    )

    all_requests = client.get("/api/v1/part_requests").json()
    assert len(all_requests) == 1

    wrong = client.get(
        "/api/v1/part_requests?conversation_id=00000000-0000-0000-0000-000000000000"
    ).json()
    assert wrong == []


def test_get_part_request_detail(client, db_session):
    conversation_id = _make_conversation(client, db_session)
    client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"sender_type": "customer", "content": "Нужны колодки на BMW X5"},
    )
    part_request_id = client.get(
        f"/api/v1/part_requests?conversation_id={conversation_id}"
    ).json()[0]["id"]

    resp = client.get(f"/api/v1/part_requests/{part_request_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == part_request_id
    assert data["customer_name"] == "Иван Петров"
    assert data["vehicle"]["brand"] == "BMW"


def test_get_part_request_missing_404(client, db_session):
    import uuid

    resp = client.get(f"/api/v1/part_requests/{uuid.uuid4()}")
    assert resp.status_code == 404


def test_patch_part_request_status(client, db_session):
    conversation_id = _make_conversation(client, db_session)
    client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"sender_type": "customer", "content": "Нужны колодки на BMW X5"},
    )
    part_request_id = client.get(
        f"/api/v1/part_requests?conversation_id={conversation_id}"
    ).json()[0]["id"]

    resp = client.patch(
        f"/api/v1/part_requests/{part_request_id}", json={"status": "quoted"}
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "quoted"

    bad = client.patch(
        f"/api/v1/part_requests/{part_request_id}", json={"status": "bogus"}
    )
    assert bad.status_code == 422
