from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from shared.pack import PackState
from shared.workflow import Workflow
from sqlalchemy import select

from app.core.config import settings
from app.models import AgentAction
from app.services.pack_service import PackService
from app.services.workflow_service import WorkflowRuntime

MANIFEST = {
    "name": "autoparts",
    "version": "1.0.0",
    "display_name": "AutoParts",
    "agents": [{"type": "intake"}, {"type": "search"}, {"type": "order"}],
    "permissions": [],
    "workflows": [{"name": "sales_pipeline"}],
    "tools": [],
    "required_core_version": ">=0.5.0",
}

WORKFLOW = {
    "name": "sales_pipeline",
    "version": "1.0.0",
    "start": "intake",
    "nodes": [
        {"id": "intake", "type": "agent", "agent": "intake", "next": "classify"},
        {
            "id": "classify",
            "type": "condition",
            "expression": "context.get('requires_search', False)",
            "branches": {"true": "search", "false": "human"},
        },
        {"id": "search", "type": "agent", "agent": "search", "next": "done"},
        {"id": "human", "type": "end", "message": "Передано менеджеру"},
        {"id": "done", "type": "end"},
    ],
}


class _PackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/internal/pack/manifest":
            body = json.dumps({"name": "autoparts", "version": "1.0.0", "manifest": MANIFEST}).encode()
            self._json(200, body)
        elif self.path == "/internal/pack/workflows":
            body = json.dumps({"workflows": [WORKFLOW]}).encode()
            self._json(200, body)
        elif self.path == "/internal/health":
            self._json(200, b"")
        else:
            self._json(404, b"")

    def do_POST(self):
        if self.path == "/internal/agents/execute":
            length = int(self.headers.get("Content-Length", 0) or 0)
            payload = json.loads(self.rfile.read(length))
            agent_type = payload.get("agent_type")
            if agent_type == "intake":
                data = {"requires_search": True, "context": {"query": payload.get("input_data", {}).get("query", "")}}
            elif agent_type == "search":
                data = {"found": True, "parts": ["A001"]}
            else:
                data = {}
            body = json.dumps(
                {
                    "response": f"{agent_type} done",
                    "data": data,
                    "handoff_agent": None,
                    "routing_decision": {"engine": agent_type},
                }
            ).encode()
            self._json(200, body)
        elif self.path == "/internal/pack/migrate":
            self._json(200, json.dumps({"ok": True, "revision": "abc"}).encode())
        else:
            self._json(404, b"")

    def _json(self, status: int, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture
def pack_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _PackHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.fixture
def active_pack(db_session, pack_server, monkeypatch):
    monkeypatch.setattr(settings, "pack_base_urls", [pack_server])
    service = PackService(db_session)
    service.discover()
    pack = service.enable("autoparts")
    assert pack.state == PackState.active
    return pack


def _make_task(db_session):
    from app.models import Company, Task

    company = db_session.scalars(select(Company)).first()
    task = Task(
        company_id=company.id,
        agent_id=None,
        title="Поиск запчасти",
        objective="Найди и предложи цену",
        input_data={"query": "тормозные колодки"},
        priority="normal",
    )
    db_session.add(task)
    db_session.commit()
    return task


def test_workflow_runs_through_agents_and_conditions(db_session, active_pack):
    runtime = WorkflowRuntime(db_session)
    workflow = runtime.load_named(active_pack, "sales_pipeline")
    task = _make_task(db_session)
    result = runtime.run(task, workflow)
    assert result["status"] == "completed"
    steps = result["steps"]
    types = [s["type"] for s in steps]
    assert types == ["agent", "condition", "agent", "end"]
    assert steps[2]["output"]["data"]["found"] is True


def test_workflow_condition_false_branches_to_human(db_session, active_pack):
    runtime = WorkflowRuntime(db_session)
    workflow = Workflow.model_validate(
        {
            "name": "classify_only",
            "version": "1.0.0",
            "start": "classify",
            "nodes": [
                {
                    "id": "classify",
                    "type": "condition",
                    "expression": "context.get('requires_search', False)",
                    "branches": {"true": "search", "false": "human"},
                },
                {"id": "search", "type": "agent", "agent": "search", "next": "done"},
                {"id": "human", "type": "end", "message": "Передано менеджеру"},
                {"id": "done", "type": "end"},
            ],
        }
    )
    task = _make_task(db_session)
    result = runtime.run(task, workflow, {"requires_search": False})
    steps = result["steps"]
    types = [s["type"] for s in steps]
    assert types == ["condition", "end"]
    assert steps[1]["message"] == "Передано менеджеру"


def test_workflow_threads_context_between_agent_nodes(db_session, active_pack, monkeypatch):
    """Progressive pipelines: data found by an earlier agent node must reach
    the next one (the Beauty/booking use case), not just the original
    task input_data."""
    seen_inputs: list[dict] = []

    def _capture(agent_type: str, input_data: dict):
        if agent_type == "reception":
            return {"service": "haircut", "day": "2026-08-25", "slot_found": True}
        if agent_type == "calendar":
            seen_inputs.append(input_data)
            return {"slot": {"id": "s1"}, "slot_found": True}
        return {}

    captured = {"inputs": seen_inputs}

    class _ProgHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/internal/pack/manifest":
                body = json.dumps(
                    {
                        "name": "beauty",
                        "version": "1.0.0",
                        "manifest": {
                            "name": "beauty",
                            "version": "1.0.0",
                            "agents": [
                                {"type": "reception"},
                                {"type": "calendar"},
                            ],
                            "workflows": [{"name": "booking_pipeline"}],
                            "required_core_version": ">=0.5.0",
                        },
                    }
                ).encode()
                self._json(200, body)
            elif self.path == "/internal/pack/workflows":
                body = json.dumps(
                    {
                        "workflows": [
                            {
                                "name": "booking_pipeline",
                                "version": "1.0.0",
                                "start": "reception",
                                "nodes": [
                                    {"id": "reception", "type": "agent", "agent": "reception", "next": "calendar"},
                                    {"id": "calendar", "type": "agent", "agent": "calendar", "next": "done"},
                                    {"id": "done", "type": "end"},
                                ],
                            }
                        ]
                    }
                ).encode()
                self._json(200, body)
            elif self.path == "/internal/health":
                self._json(200, b"")
            else:
                self._json(404, b"")

        def do_POST(self):
            if self.path == "/internal/agents/execute":
                length = int(self.headers.get("Content-Length", 0) or 0)
                payload = json.loads(self.rfile.read(length))
                data = _capture(payload.get("agent_type"), payload.get("input_data", {}))
                body = json.dumps(
                    {
                        "response": f"{payload.get('agent_type')} done",
                        "data": data,
                        "handoff_agent": None,
                        "routing_decision": {"engine": payload.get("agent_type")},
                    }
                ).encode()
                self._json(200, body)
            else:
                self._json(404, b"")

        def _json(self, status: int, body: bytes) -> None:
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if body:
                self.wfile.write(body)

        def log_message(self, *args):
            pass

    server2 = ThreadingHTTPServer(("127.0.0.1", 0), _ProgHandler)
    thread2 = threading.Thread(target=server2.serve_forever, daemon=True)
    thread2.start()
    try:
        beauty_url = f"http://127.0.0.1:{server2.server_address[1]}"
        monkeypatch.setattr(settings, "pack_base_urls", [beauty_url])
        PackService(db_session).discover()
        pack = PackService(db_session).enable("beauty")

        runtime = WorkflowRuntime(db_session)
        workflow = runtime.load_named(pack, "booking_pipeline")
        task = _make_task(db_session)
        task.input_data = {"customer_name": "Ирина"}
        db_session.add(task)
        db_session.commit()
        result = runtime.run(task, workflow)

        assert result["status"] == "completed"
        assert captured["inputs"], "calendar node не получил input_data"
        cal_input = captured["inputs"][0]
        assert cal_input["customer_name"] == "Ирина"
        assert cal_input["service"] == "haircut"
        assert cal_input["day"] == "2026-08-25"
    finally:
        server2.shutdown()
        server2.server_close()
        thread2.join(timeout=5)


def test_workflow_dispatches_to_owning_pack_on_agent_type_collision(
    db_session, active_pack, monkeypatch
):
    """Two verticals declaring the same agent type (``sales``) must not
    collide: a beauty workflow's sales node goes to beauty, not autoparts."""
    hits: list[str] = []

    class _CollisionHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/internal/pack/manifest":
                body = json.dumps(
                    {
                        "name": "beauty",
                        "version": "1.0.0",
                        "manifest": {
                            "name": "beauty",
                            "version": "1.0.0",
                            "agents": [{"type": "sales"}],
                            "workflows": [{"name": "booking_pipeline"}],
                            "required_core_version": ">=0.5.0",
                        },
                    }
                ).encode()
                self._json(200, body)
            elif self.path == "/internal/pack/workflows":
                body = json.dumps(
                    {
                        "workflows": [
                            {
                                "name": "booking_pipeline",
                                "version": "1.0.0",
                                "start": "sales",
                                "nodes": [
                                    {"id": "sales", "type": "agent", "agent": "sales", "next": "done"},
                                    {"id": "done", "type": "end"},
                                ],
                            }
                        ]
                    }
                ).encode()
                self._json(200, body)
            elif self.path == "/internal/health":
                self._json(200, b"")
            else:
                self._json(404, b"")

        def do_POST(self):
            if self.path == "/internal/agents/execute":
                hits.append("beauty")
                body = json.dumps(
                    {
                        "response": "beauty sales done",
                        "data": {"booking_id": "b1"},
                        "handoff_agent": None,
                        "routing_decision": {"engine": "sales"},
                    }
                ).encode()
                self._json(200, body)
            else:
                self._json(404, b"")

        def _json(self, status: int, body: bytes) -> None:
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if body:
                self.wfile.write(body)

        def log_message(self, *args):
            pass

    server2 = ThreadingHTTPServer(("127.0.0.1", 0), _CollisionHandler)
    thread2 = threading.Thread(target=server2.serve_forever, daemon=True)
    thread2.start()
    try:
        beauty_url = f"http://127.0.0.1:{server2.server_address[1]}"
        monkeypatch.setattr(settings, "pack_base_urls", [beauty_url])
        PackService(db_session).discover()
        beauty_pack = PackService(db_session).enable("beauty")

        # autoparts already active (fixture) and also provides "sales";
        # it must NOT win now that the workflow knows its owning pack.
        runtime = WorkflowRuntime(db_session)
        workflow = runtime.load_named(beauty_pack, "booking_pipeline")
        task = _make_task(db_session)
        result = runtime.run(task, workflow, owning_pack=beauty_pack)

        assert result["status"] == "completed"
        assert hits == ["beauty"], f"ожидали только beauty, получили: {hits}"
        assert result["steps"][0]["output"]["data"]["booking_id"] == "b1"
    finally:
        server2.shutdown()
        server2.server_close()
        thread2.join(timeout=5)


def test_workflow_human_node_records_action(db_session, active_pack):
    runtime = WorkflowRuntime(db_session)
    workflow = Workflow.model_validate(
        {
            "name": "with_human",
            "version": "1.0.0",
            "start": "ask",
            "nodes": [
                {"id": "ask", "type": "human", "message": "Согласуйте цену", "next": "done"},
                {"id": "done", "type": "end"},
            ],
        }
    )
    task = _make_task(db_session)
    result = runtime.run(task, workflow)
    assert result["status"] == "awaiting_approval"
    assert result["paused_at"] == "ask"
    action = db_session.scalars(select(AgentAction)).first()
    assert action is not None
    assert action.action_type == "workflow_human"
    assert action.requires_approval is True


def test_workflow_load_invalid_rejected(db_session, monkeypatch):
    class _BadHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/internal/pack/manifest":
                body = json.dumps({"name": "autoparts", "version": "1.0.0", "manifest": MANIFEST}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif self.path == "/internal/pack/workflows":
                body = json.dumps({"workflows": [{"name": "bad", "start": "missing", "nodes": []}]}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif self.path == "/internal/health":
                self.send_response(200)
                self.send_header("Content-Length", "0")
                self.end_headers()
            else:
                self.send_response(404)
                self.send_header("Content-Length", "0")
                self.end_headers()

        def log_message(self, *args):
            pass

    server2 = ThreadingHTTPServer(("127.0.0.1", 0), _BadHandler)
    thread2 = threading.Thread(target=server2.serve_forever, daemon=True)
    thread2.start()
    try:
        bad_url = f"http://127.0.0.1:{server2.server_address[1]}"
        monkeypatch.setattr(settings, "pack_base_urls", [bad_url])
        PackService(db_session).discover()
        pack = PackService(db_session).enable("autoparts")

        from app.services.workflow_service import WorkflowRuntimeError

        runtime = WorkflowRuntime(db_session)
        with pytest.raises(WorkflowRuntimeError):
            runtime.load_from_pack(pack)
    finally:
        server2.shutdown()
        server2.server_close()
        thread2.join(timeout=5)
