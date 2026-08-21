from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from shared.pack import PackState, compute_checksum, parse_manifest
from sqlalchemy import select

from app.core.config import settings
from app.models import Pack
from app.services.pack_service import PackError, PackService

MANIFEST = {
    "name": "autoparts",
    "version": "1.0.0",
    "display_name": "AutoParts",
    "agents": [{"type": "search"}, {"type": "intake"}],
    "permissions": ["supplier.search"],
    "workflows": [{"name": "sales_pipeline"}],
    "tools": ["supplier_search"],
    "required_core_version": ">=0.5.0",
}


class _PackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/internal/pack/manifest":
            import json

            body = json.dumps({"name": "autoparts", "version": "1.0.0", "manifest": MANIFEST}).encode()
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

    def do_POST(self):
        if self.path == "/internal/pack/migrate":
            import json

            body = json.dumps({"ok": True, "revision": "abc123"}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()

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


def test_discover_registers_pack(db_session, pack_server, monkeypatch):
    monkeypatch.setattr(settings, "pack_base_urls", [pack_server])
    results = PackService(db_session).discover()
    assert results[0]["ok"] is True
    pack = db_session.scalars(select(Pack)).first()
    assert pack.name == "autoparts"
    assert pack.version == "1.0.0"
    assert pack.state == PackState.installed
    assert pack.is_active is False


def test_enable_sets_active(db_session, pack_server, monkeypatch):
    monkeypatch.setattr(settings, "pack_base_urls", [pack_server])
    PackService(db_session).discover()
    pack = PackService(db_session).enable("autoparts")
    assert pack.state == PackState.active
    assert pack.is_active is True


def test_enable_syncs_pack_agents(db_session, pack_server, monkeypatch):
    monkeypatch.setattr(settings, "pack_base_urls", [pack_server])
    PackService(db_session).discover()
    PackService(db_session).enable("autoparts")
    from app.models import Agent

    slugs = [
        a.slug for a in db_session.scalars(select(Agent)).all()
        if a.slug.startswith("autoparts-")
    ]
    assert "autoparts-search-agent" in slugs
    assert "autoparts-intake-agent" in slugs


def test_healthcheck_sync_is_idempotent(db_session, pack_server, monkeypatch):
    monkeypatch.setattr(settings, "pack_base_urls", [pack_server])
    service = PackService(db_session)
    service.discover()
    service.enable("autoparts")
    service.healthcheck("autoparts")
    service.healthcheck("autoparts")
    from app.models import Agent

    count = len(
        [
            a for a in db_session.scalars(select(Agent)).all()
            if a.slug.startswith("autoparts-")
        ]
    )
    assert count == 2


def test_disable_sets_disabled(db_session, pack_server, monkeypatch):
    monkeypatch.setattr(settings, "pack_base_urls", [pack_server])
    PackService(db_session).discover()
    service = PackService(db_session)
    service.enable("autoparts")
    pack = service.disable("autoparts")
    assert pack.state == PackState.disabled
    assert pack.is_active is False


def test_healthcheck_ok(db_session, pack_server, monkeypatch):
    monkeypatch.setattr(settings, "pack_base_urls", [pack_server])
    PackService(db_session).discover()
    result = PackService(db_session).healthcheck("autoparts")
    assert result["health"] == "ok"
    pack = db_session.scalars(select(Pack)).first()
    assert pack.last_health_ok is True


def test_register_incompatible_core(db_session, monkeypatch):
    monkeypatch.setattr(settings, "core_version", "0.4.0")
    with pytest.raises(PackError):
        PackService(db_session).register_manifest(
            "http://localhost:9", {**MANIFEST, "required_core_version": ">=0.5.0"}
        )


def test_upgrade_version_marks_upgrade_required(db_session, pack_server, monkeypatch):
    monkeypatch.setattr(settings, "pack_base_urls", [pack_server])
    service = PackService(db_session)
    service.discover()
    pack = db_session.scalars(select(Pack)).first()
    assert pack.state == PackState.installed

    newer = dict(MANIFEST)
    newer["version"] = "2.0.0"

    class _NewerHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/internal/pack/manifest":
                import json

                body = json.dumps({"name": "autoparts", "version": "2.0.0", "manifest": newer}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_response(404)
                self.send_header("Content-Length", "0")
                self.end_headers()

        def log_message(self, *args):
            pass

    server2 = ThreadingHTTPServer(("127.0.0.1", 0), _NewerHandler)
    thread2 = threading.Thread(target=server2.serve_forever, daemon=True)
    thread2.start()
    try:
        service.discover_one(f"http://127.0.0.1:{server2.server_address[1]}")
    finally:
        server2.shutdown()
        server2.server_close()
        thread2.join(timeout=5)

    db_session.refresh(pack)
    assert pack.version == "2.0.0"
    assert pack.state == PackState.upgrade_required


def test_configure_sets_config(db_session, pack_server, monkeypatch):
    monkeypatch.setattr(settings, "pack_base_urls", [pack_server])
    service = PackService(db_session)
    service.discover()
    pack = service.configure("autoparts", {"region": "ru", "suppliers": ["rossko"]})
    assert pack.state == PackState.configured
    assert pack.config == {"region": "ru", "suppliers": ["rossko"]}


def test_upgrade_runs_migrate_and_returns_configured(db_session, pack_server, monkeypatch):
    monkeypatch.setattr(settings, "pack_base_urls", [pack_server])
    service = PackService(db_session)
    service.discover()
    pack = service.upgrade("autoparts")
    assert pack.state == PackState.configured  # not active yet


def test_uninstall_removes_pack(db_session, pack_server, monkeypatch):
    monkeypatch.setattr(settings, "pack_base_urls", [pack_server])
    service = PackService(db_session)
    service.discover()
    assert db_session.scalars(select(Pack)).first() is not None
    service.uninstall("autoparts")
    assert db_session.scalars(select(Pack)).first() is None


def test_transition_guard_blocks_illegal_enable_after_uninstall_state(
    db_session, pack_server, monkeypatch
):
    monkeypatch.setattr(settings, "pack_base_urls", [pack_server])
    service = PackService(db_session)
    service.discover()
    service.enable("autoparts")
    service.disable("autoparts")
    # disable -> disabled; re-enable is allowed (disabled is in enable's set).
    pack = service.enable("autoparts")
    assert pack.state == PackState.active


def test_enable_from_installed_allowed(db_session, pack_server, monkeypatch):
    monkeypatch.setattr(settings, "pack_base_urls", [pack_server])
    service = PackService(db_session)
    service.discover()
    pack = service.enable("autoparts")
    assert pack.state == PackState.active


def test_full_lifecycle_sequence(db_session, pack_server, monkeypatch):
    monkeypatch.setattr(settings, "pack_base_urls", [pack_server])
    service = PackService(db_session)
    service.discover()  # installed
    service.configure("autoparts", {"region": "ru"})  # configured
    service.upgrade("autoparts")  # stays configured (not active)
    pack = service.enable("autoparts")  # active
    assert pack.state == PackState.active
    service.disable("autoparts")  # disabled
    service.enable("autoparts")  # active again
    service.uninstall("autoparts")  # gone
    assert db_session.scalars(select(Pack)).first() is None


def test_register_stores_registry_metadata(db_session, monkeypatch):
    manifest = parse_manifest(
        {
            "name": "billing",
            "version": "1.0.0",
            "display_name": "Billing",
            "developer": "AgentOS Labs",
            "homepage": "https://agentos.local/billing",
            "license": "Apache-2.0",
            "dependencies": [{"name": "autoparts", "version_req": ">=1.0.0"}],
            "agents": [{"type": "invoice"}],
        }
    )
    pack = PackService(db_session).register("http://localhost:9", manifest)
    assert pack.developer == "AgentOS Labs"
    assert pack.homepage == "https://agentos.local/billing"
    assert pack.license == "Apache-2.0"
    assert pack.dependencies == [{"name": "autoparts", "version_req": ">=1.0.0"}]
    assert pack.checksum == compute_checksum(manifest)
    assert pack.signature == ""


def test_register_with_checksum_verified(db_session, monkeypatch):
    base = {
        "name": "billing",
        "version": "1.0.0",
        "agents": [{"type": "invoice"}],
    }
    manifest = parse_manifest({**base, "checksum": compute_checksum(parse_manifest(base))})
    pack = PackService(db_session).register("http://localhost:9", manifest)
    assert pack.checksum == manifest.checksum


def test_register_with_wrong_checksum_rejected(db_session, monkeypatch):
    manifest = parse_manifest(
        {
            "name": "billing",
            "version": "1.0.0",
            "agents": [{"type": "invoice"}],
            "checksum": "deadbeef",
        }
    )
    with pytest.raises(PackError):
        PackService(db_session).register("http://localhost:9", manifest)


def test_to_dict_includes_registry(db_session, monkeypatch):
    manifest = parse_manifest(
        {
            "name": "billing",
            "version": "1.0.0",
            "developer": "AgentOS Labs",
            "license": "Apache-2.0",
            "agents": [{"type": "invoice"}],
        }
    )
    pack = PackService(db_session).register("http://localhost:9", manifest)
    data = PackService(db_session).to_dict(pack)
    assert data["developer"] == "AgentOS Labs"
    assert data["license"] == "Apache-2.0"
    assert "dependencies" in data
    assert "checksum" in data
    assert "signature" in data


def test_register_stores_routes(db_session, monkeypatch):
    manifest = parse_manifest(
        {
            "name": "autoparts",
            "version": "1.0.0",
            "routes": [{"prefix": "/autoparts", "service": "autoparts"}],
            "agents": [{"type": "intake"}],
        }
    )
    pack = PackService(db_session).register("http://localhost:9", manifest)
    assert pack.routes == [{"prefix": "/autoparts", "service": "autoparts"}]
    data = PackService(db_session).to_dict(pack)
    assert data["routes"] == [{"prefix": "/autoparts", "service": "autoparts"}]


def test_enable_requires_active_dependency(db_session, pack_server, monkeypatch):
    monkeypatch.setattr(settings, "pack_base_urls", [pack_server])
    service = PackService(db_session)
    service.discover()  # autoparts installed (not active)
    dependent = parse_manifest(
        {
            "name": "billing",
            "version": "1.0.0",
            "dependencies": [{"name": "autoparts", "version_req": ">=1.0.0"}],
            "agents": [{"type": "invoice"}],
        }
    )
    service.register("http://localhost:9", dependent)
    with pytest.raises(PackError, match="не активна"):
        service.enable("billing")


def test_enable_with_unsatisfied_dependency_version(db_session, pack_server, monkeypatch):
    monkeypatch.setattr(settings, "pack_base_urls", [pack_server])
    service = PackService(db_session)
    service.discover()
    service.enable("autoparts")  # 1.0.0
    dependent = parse_manifest(
        {
            "name": "billing",
            "version": "1.0.0",
            "dependencies": [{"name": "autoparts", "version_req": ">=2.0.0"}],
            "agents": [{"type": "invoice"}],
        }
    )
    service.register("http://localhost:9", dependent)
    with pytest.raises(PackError, match="не удовлетворяет"):
        service.enable("billing")


def test_enable_with_satisfied_dependency(db_session, pack_server, monkeypatch):
    monkeypatch.setattr(settings, "pack_base_urls", [pack_server])
    service = PackService(db_session)
    service.discover()
    service.enable("autoparts")
    dependent = parse_manifest(
        {
            "name": "billing",
            "version": "1.0.0",
            "dependencies": [{"name": "autoparts", "version_req": ">=1.0.0"}],
            "agents": [{"type": "invoice"}],
        }
    )
    service.register(pack_server, dependent)
    pack = service.enable("billing")
    assert pack.state == PackState.active
    assert pack.is_active is True
