"""Tests for the Beauty pack (sprint 5.5).

Pure-SDK agents and tools are tested directly — no database, no core. The
workflow file is validated with the shared Workflow SDK.
"""

from __future__ import annotations

import pathlib

import pytest
from shared.agents import run_agent
from shared.workflow import load_workflow

from app.agents.registry import agent_registry, get_class
from app.salon import state


@pytest.fixture(autouse=True)
def reset_salon():

    state._slots = []
    state._bookings = {}
    yield
    state._slots = []
    state._bookings = {}


def _run(kind: str, objective: str, input_data: dict | None = None):
    agent = get_class(kind)()
    ctx = agent.build_context(objective, input_data or {})
    return run_agent(agent, ctx)


def test_registry_describes_all_beauty_agents():
    kinds = agent_registry.kinds()
    assert set(kinds) == {"reception", "calendar", "booking", "sales", "reminder"}
    info = agent_registry.get("booking").describe()
    assert info["kind"] == "booking"
    assert "booking.create" in info["permissions"]


def test_reception_detects_service_and_date():
    out = _run(
        "reception",
        "Запишите меня на стрижку 2026-08-25",
        {"customer_name": "Ирина"},
    )
    assert out.data["has_service"] is True
    assert out.data["service"] == "haircut"
    assert out.data["has_date"] is True
    assert out.data["day"] == "2026-08-25"


def test_reception_missing_service_prompts():
    out = _run("reception", "Запишите меня на завтра")
    assert out.data["has_service"] is False


def test_calendar_finds_free_slot():
    out = _run("calendar", "Слот на завтра", {"day": "2026-08-25", "service": "haircut"})
    assert out.data["slot_found"] is True
    slot = out.data["slot"]
    assert slot["day"] == "2026-08-25"
    assert slot["master"] in {"Анна", "Мария", "Ольга"}


def test_booking_books_slot():
    slot_out = _run("calendar", "", {"day": "2026-08-25", "service": "haircut"})
    slot = slot_out.data["slot"]
    out = _run(
        "booking",
        "Забронировать",
        {"slot": slot, "customer_name": "Ирина", "service": "haircut"},
    )
    assert out.data["booking_id"]
    assert out.data["booking"]["customer_name"] == "Ирина"


def test_sales_confirms_with_upsell():
    booking = _booking("Ирина")
    out = _run("sales", "Подтвердить", {"booking": booking})
    assert out.data["price"] == 1500
    assert "укладка" in out.data["upsell"]
    assert out.data["confirmation"]


def test_reminder_schedules():
    booking = _booking("Ирина")
    out = _run(
        "reminder",
        "Напомнить",
        {"booking": booking, "reminder_hours_before": 3},
    )
    assert out.data["reminder"]["reminder_hours_before"] == 3
    assert out.data["reminder"]["booking_id"] == booking["booking_id"]


def test_full_pipeline_returns_booking_and_reminder():
    """End-to-end through the SDK contract, same as the workflow DAG."""
    reception = _run(
        "reception",
        "Стрижка 2026-08-25",
        {"customer_name": "Ирина"},
    )
    assert reception.data["has_service"] and reception.data["has_date"]

    calendar = _run(
        "calendar",
        "",
        {"day": reception.data["day"], "service": reception.data["service"]},
    )
    assert calendar.data["slot_found"]

    booking = _run(
        "booking",
        "",
        {
            "slot": calendar.data["slot"],
            "customer_name": "Ирина",
            "service": reception.data["service"],
        },
    )
    assert booking.data["booking_id"]

    sales = _run("sales", "", {"booking": booking.data["booking"]})
    assert sales.data["booking_id"]

    reminder = _run(
        "reminder",
        "",
        {"booking": booking.data["booking"], "reminder_hours_before": 2},
    )
    assert reminder.data["reminder"]["booking_id"] == booking.data["booking_id"]


def test_booking_denied_without_permission_scope():
    """BookingAgent requires calendar.write+booking.create; a gate that has
    none must raise (the ctx permission facade is manifest-driven)."""
    from app.agents.booking import BookingAgent

    agent = BookingAgent()
    ctx = agent.build_context("", {})
    ctx.permissions = _EmptyPermissions()
    with pytest.raises(PermissionError):
        agent.execute(ctx)


class _EmptyPermissions:
    def require(self, *permissions: str) -> None:
        raise PermissionError("denied")

    def has(self, permission: str) -> bool:
        return False

    def allowed(self) -> list[str]:
        return []


def test_booking_pipeline_workflow_file_validates():
    path = pathlib.Path(__file__).resolve().parents[1] / "workflows" / "booking_pipeline.yaml"
    workflow = load_workflow(path)
    assert workflow.name == "booking_pipeline"
    assert workflow.start == "reception"
    node_ids = [n.id for n in workflow.nodes]
    assert node_ids == [
        "reception",
        "classify",
        "calendar",
        "slot_check",
        "booking",
        "sales",
        "reminder",
        "human",
        "done",
    ]
    assert workflow.node("classify").branches == {"true": "calendar", "false": "human"}


def _booking(customer: str) -> dict:
    slot_out = _run("calendar", "", {"day": "2026-08-25", "service": "haircut"})
    out = _run(
        "booking",
        "",
        {"slot": slot_out.data["slot"], "customer_name": customer, "service": "haircut"},
    )
    return out.data["booking"]
