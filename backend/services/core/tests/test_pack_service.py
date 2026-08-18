from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from shared.pack import PackState
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


def test_disable_sets_disabled(db_session, pack_server, monkeypatch):
    monkeypatch.setattr(settings, "pack_base_urls", [pack_server])
    PackService(db_session).discover()
    pack = PackService(db_session).disable("autoparts")
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
