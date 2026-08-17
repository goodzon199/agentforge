from __future__ import annotations

from sqlalchemy import select

from app.core.seeding import (
    DEMO_CATALOG_FITMENTS,
    DEMO_COMPANY_SLUG,
    DEMO_CROSS_REFERENCES,
)
from app.models import (
    CatalogFitment,
    Company,
    CrossReference,
    PartFitmentEvidence,
    PartRequest,
    Vehicle,
)
from app.models.enums import PartRequestStatus
from app.services.fitment_service import FitmentService
from app.services.vin_decode import check_digit, decode_vin, normalize_vin


def _company_id(db_session):
    return db_session.scalars(select(Company).where(Company.slug == DEMO_COMPANY_SLUG)).first().id


def _valid_vin(brand: str = "BMW", year_code: str = "J") -> str:
    """Build a VIN that passes the ISO 3779 check digit."""
    head = "WBAKX410"  # WMI for BMW + VDS start (8 chars, pos 1-8)
    tail = year_code + "1234567"  # pos 10-17 (8 chars)
    cd = check_digit(head + "0" + tail)
    return head + (cd or "0") + tail


def _vehicle(db_session, company_id, *, brand="BMW", model="X5", year=2016, vin=None):
    v = Vehicle(
        company_id=company_id,
        customer_id=_customer_id(db_session, company_id),
        brand=brand,
        model=model,
        year=year,
        vin=vin or _valid_vin(),
    )
    db_session.add(v)
    db_session.flush()
    return v


def _customer_id(db_session, company_id):
    from app.services.conversation_service import ConversationService

    cs = ConversationService(db_session)
    customer = cs.create_customer(company_id=company_id, name="Иван Петров")
    db_session.add(customer)
    db_session.flush()
    return customer.id


def _part_request(db_session, company_id, *, article="GDB3410", vehicle=None, structured=None):
    from app.services.conversation_service import ConversationService

    cs = ConversationService(db_session)
    customer = cs.create_customer(company_id=company_id, name="Иван Петров")
    db_session.add(customer)
    db_session.flush()
    conversation = cs.create_conversation(
        company_id=company_id, customer_id=customer.id, channel="web"
    )
    db_session.add(conversation)
    db_session.flush()
    pr = PartRequest(
        company_id=company_id,
        conversation_id=conversation.id,
        customer_id=customer.id,
        part_name="Тормозные колодки",
        article=article,
        quantity=1,
        status=PartRequestStatus.ready_for_search,
        missing_fields=[],
        vehicle_id=vehicle.id if vehicle is not None else None,
        structured_data=structured or {"intent_confidence": 0.9},
    )
    db_session.add(pr)
    db_session.flush()
    return pr


# --- VIN decode -------------------------------------------------------------


def test_check_digit_round_trip():
    vin = _valid_vin()
    assert len(vin) == 17
    assert decode_vin(vin).valid is True
    assert decode_vin(vin).brand == "BMW"


def test_check_digit_rejects_mutation():
    vin = _valid_vin()
    mutated = vin[:5] + ("1" if vin[5] != "1" else "2") + vin[6:]
    assert decode_vin(mutated).valid is False


def test_normalize_vin_strips_illegal_chars():
    assert normalize_vin("wba 1234") == "WBA1234"


def test_year_decode():
    # The latest 30-year cycle wins (a 10th-char 'J' is 2018, not 1988).
    assert decode_vin(_valid_vin(year_code="J")).year == 2018
    assert decode_vin(_valid_vin(year_code="1")).year == 2001


# --- Fitment Engine ---------------------------------------------------------


def test_article_only_no_vehicle_is_na(db_session):
    company_id = _company_id(db_session)
    pr = _part_request(db_session, company_id, vehicle=None)

    result = FitmentService(db_session).evaluate(pr)

    assert result.vehicle_dependent is False
    assert result.confidence == 1.0
    assert result.verdict == "na"


def test_vehicle_with_catalog_cross_confirmed(db_session):
    company_id = _company_id(db_session)
    vehicle = _vehicle(db_session, company_id)
    pr = _part_request(db_session, company_id, vehicle=vehicle)

    result = FitmentService(db_session).evaluate(pr)

    assert result.vehicle_dependent is True
    assert result.confidence > 0.5
    assert any(s.source == "catalog" for s in result.sources)
    assert any(s.source == "cross" for s in result.sources)


def test_vehicle_with_unknown_article_is_uncertain(db_session):
    company_id = _company_id(db_session)
    vehicle = _vehicle(db_session, company_id)
    pr = _part_request(db_session, company_id, article="NO-SUCH-ARTICLE", vehicle=vehicle)

    result = FitmentService(db_session).evaluate(pr)

    assert result.vehicle_dependent is True
    assert result.confidence < 0.5
    assert result.verdict == "uncertain"


def test_vehicle_year_out_of_catalog_range_not_confirmed(db_session):
    company_id = _company_id(db_session)
    vehicle = _vehicle(db_session, company_id, year=2024)  # catalog range ends 2018
    pr = _part_request(db_session, company_id, vehicle=vehicle)

    result = FitmentService(db_session).evaluate(pr)

    assert result.confidence < 0.5
    assert result.verdict == "uncertain"


def test_return_drags_confidence_below_half(db_session):
    company_id = _company_id(db_session)
    vehicle = _vehicle(db_session, company_id)
    pr = _part_request(db_session, company_id, vehicle=vehicle)
    FitmentService(db_session).record_return(
        pr, reason="колодки не подошли по посадочным", status="returned"
    )
    db_session.commit()

    result = FitmentService(db_session).evaluate(pr)

    assert any(s.source == "return" for s in result.sources)
    assert result.confidence < 0.5
    assert result.verdict == "uncertain"


def test_order_evidence_pushes_confidence_high(db_session):
    """Learning moat: an order for the same vehicle+article makes the engine
    confident enough for Controlled Auto (>0.9) even without fresh catalog."""
    company_id = _company_id(db_session)
    vehicle = _vehicle(db_session, company_id)
    pr = _part_request(db_session, company_id, vehicle=vehicle)
    db_session.add(
        PartFitmentEvidence(
            company_id=company_id,
            part_request_id=pr.id,
            vehicle_id=vehicle.id,
            article="GDB3410",
            brand="TRW",
            source="order_history",
            confidence=1.0,
            detail={"order_number": "ORD-0001"},
        )
    )
    db_session.commit()

    result = FitmentService(db_session).evaluate(pr)

    assert any(s.source == "evidence" for s in result.sources)
    assert result.confidence >= 0.9
    assert result.verdict == "confirmed"


def test_snapshot_persists_engine_result(db_session):
    company_id = _company_id(db_session)
    vehicle = _vehicle(db_session, company_id)
    pr = _part_request(db_session, company_id, vehicle=vehicle)

    snap = FitmentService(db_session).snapshot(pr)

    assert snap["engine_version"] == "4.0.0"
    assert "confidence" in snap
    assert snap["vehicle_dependent"] is True
    assert isinstance(snap["sources"], list)


# --- Seeded knowledge -------------------------------------------------------


def test_demo_catalog_seeded(db_session):
    company_id = _company_id(db_session)
    rows = db_session.scalars(
        select(CatalogFitment).where(CatalogFitment.company_id == company_id)
    ).all()
    assert len(rows) == len(DEMO_CATALOG_FITMENTS)
    assert any(r.article == "GDB3410" and r.vehicle_model == "X5" for r in rows)


def test_demo_cross_references_seeded(db_session):
    company_id = _company_id(db_session)
    rows = db_session.scalars(
        select(CrossReference).where(CrossReference.company_id == company_id)
    ).all()
    assert len(rows) == len(DEMO_CROSS_REFERENCES)


# --- Sprint 4.1: explainability + manager verify ----------------------------


def _manager_user(db_session, company_id):
    import uuid

    from app.services.user_service import UserService

    user = UserService(db_session).create(
        email=f"fitment.mgr.{uuid.uuid4().hex[:8]}@example.com",
        full_name="Менеджер Фитмент",
        password="Passw0rd!",
        role="manager",
        company_id=company_id,
    )
    db_session.flush()
    return user


def test_explain_na_request(db_session):
    company_id = _company_id(db_session)
    pr = _part_request(db_session, company_id, vehicle=None)

    expl = FitmentService(db_session).explain(pr)

    assert expl.level == "high"
    assert expl.result.verdict == "na"
    assert expl.checks


def test_explain_catalog_shows_checks_and_no_warnings(db_session):
    company_id = _company_id(db_session)
    vehicle = _vehicle(db_session, company_id)
    pr = _part_request(db_session, company_id, vehicle=vehicle)

    expl = FitmentService(db_session).explain(pr)

    assert expl.level == "medium"
    assert any("VIN" in c for c in expl.checks)
    assert any("GDB3410" in c for c in expl.checks)


def test_explain_uncertain_has_warning(db_session):
    company_id = _company_id(db_session)
    vehicle = _vehicle(db_session, company_id)
    pr = _part_request(db_session, company_id, article="NO-SUCH-ARTICLE", vehicle=vehicle)

    expl = FitmentService(db_session).explain(pr)

    assert expl.level == "low"
    assert any("требуется проверка менеджера" in w for w in expl.warnings)


def test_explain_return_is_a_warning(db_session):
    company_id = _company_id(db_session)
    vehicle = _vehicle(db_session, company_id)
    pr = _part_request(db_session, company_id, vehicle=vehicle)
    FitmentService(db_session).record_return(
        pr, reason="не подошли по посадочным", status="returned"
    )
    db_session.commit()

    expl = FitmentService(db_session).explain(pr)

    assert any("возврат" in w.lower() for w in expl.warnings)
    assert expl.level == "low"


def test_verify_confirmed_adds_evidence_and_raises_confidence(db_session):
    company_id = _company_id(db_session)
    vehicle = _vehicle(db_session, company_id)
    pr = _part_request(db_session, company_id, article="NO-SUCH-ARTICLE", vehicle=vehicle)
    user = _manager_user(db_session, company_id)
    service = FitmentService(db_session)

    before = service.evaluate(pr).confidence
    evidence = service.verify(
        pr,
        user_id=user.id,
        article="NO-SUCH-ARTICLE",
        brand="TRW",
        result="confirmed",
    )
    db_session.commit()

    assert evidence.source == "manager"
    assert evidence.result == "confirmed"
    assert evidence.user_id == user.id
    assert evidence.confidence == 1.0
    after = service.evaluate(pr).confidence
    assert after > before
    assert after >= 0.5
    assert after < 0.9
    assert (pr.structured_data or {}).get("fitment", {}).get("confidence", 0) >= 0.5


def test_verify_rejected_drags_confidence_down(db_session):
    company_id = _company_id(db_session)
    vehicle = _vehicle(db_session, company_id)
    pr = _part_request(db_session, company_id, vehicle=vehicle)
    user = _manager_user(db_session, company_id)
    service = FitmentService(db_session)

    before = service.evaluate(pr).confidence
    service.verify(
        pr,
        user_id=user.id,
        article="GDB3410",
        brand="TRW",
        result="rejected",
    )
    db_session.commit()

    after = service.evaluate(pr).confidence
    assert after < before
    assert after < 0.5
    rejected = db_session.scalars(
        select(PartFitmentEvidence).where(
            PartFitmentEvidence.part_request_id == pr.id,
            PartFitmentEvidence.result == "rejected",
        )
    ).first()
    assert rejected is not None
    assert any(s.source == "manager" and s.score == 0.0 for s in service.evaluate(pr).sources)


def test_verify_rejected_appears_in_explain_warnings(db_session):
    company_id = _company_id(db_session)
    vehicle = _vehicle(db_session, company_id)
    pr = _part_request(db_session, company_id, vehicle=vehicle)
    user = _manager_user(db_session, company_id)
    service = FitmentService(db_session)
    service.verify(pr, user_id=user.id, article="GDB3410", result="rejected")
    db_session.commit()

    expl = service.explain(pr)

    assert expl.level == "low"
    assert any("менеджер отклонил" in w for w in expl.warnings)


# --- Sprint 4.1 API: explainability endpoints --------------------------------


def _api_part_request(db_session, company_id=None):
    company_id = company_id or _company_id(db_session)
    return _part_request(db_session, company_id, vehicle=_vehicle(db_session, company_id))


def test_api_explain_na_request(client, db_session):
    company_id = _company_id(db_session)
    pr = _part_request(db_session, company_id)
    resp = client.get(f"/api/v1/fitment/{pr.id}/explain")
    assert resp.status_code == 200
    data = resp.json()
    assert data["vehicle_dependent"] is False
    assert data["verdict"] == "na"
    assert data["level"] == "high"
    assert data["checks"]


def test_api_explain_vehicle_request_shows_sources(client, db_session):
    company_id = _company_id(db_session)
    pr = _part_request(db_session, company_id, vehicle=_vehicle(db_session, company_id))
    resp = client.get(f"/api/v1/fitment/{pr.id}/explain")
    assert resp.status_code == 200
    data = resp.json()
    assert data["vehicle_dependent"] is True
    assert data["confidence"] > 0
    assert isinstance(data["sources"], list)
    sources = {s["source"] for s in data["sources"]}
    assert "catalog" in sources  # DEMO_CATALOG_FITMENTS has GDB3410 -> X5
    assert data["level"] in {"high", "medium", "low"}


def test_api_explain_unknown_request_404(client, db_session):
    import uuid

    resp = client.get(f"/api/v1/fitment/{uuid.uuid4()}/explain")
    assert resp.status_code == 404


def test_api_verify_confirmed_updates_explain(client, db_session):
    company_id = _company_id(db_session)
    pr = _part_request(db_session, company_id, vehicle=_vehicle(db_session, company_id))
    before = client.get(f"/api/v1/fitment/{pr.id}/explain").json()

    resp = client.post(
        f"/api/v1/fitment/{pr.id}/verify",
        json={"article": "GDB3410", "brand": "TRW", "result": "confirmed"},
    )
    assert resp.status_code == 200
    after = resp.json()
    assert after["confidence"] >= before["confidence"]
    assert any("подтверждено" in s["detail"] for s in after["sources"])


def test_api_verify_rejected_lowers_confidence(client, db_session):
    company_id = _company_id(db_session)
    pr = _part_request(db_session, company_id, vehicle=_vehicle(db_session, company_id))
    before = client.get(f"/api/v1/fitment/{pr.id}/explain").json()["confidence"]

    resp = client.post(
        f"/api/v1/fitment/{pr.id}/verify",
        json={"article": "GDB3410", "brand": "TRW", "result": "rejected"},
    )
    assert resp.status_code == 200
    after = resp.json()
    assert after["confidence"] < before
    assert any("менеджер отклонил" in w for w in after["warnings"])


def test_api_verify_bad_result_rejected(client, db_session):
    company_id = _company_id(db_session)
    pr = _part_request(db_session, company_id, vehicle=_vehicle(db_session, company_id))
    resp = client.post(
        f"/api/v1/fitment/{pr.id}/verify",
        json={"article": "GDB3410", "result": "maybe"},
    )
    assert resp.status_code == 422
