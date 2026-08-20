from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from shared.pack import parse_manifest

from app.services.pack_service import PackService


class _UpstreamHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/internal/health":
            self.send_response(200)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if self.path == "/api/v1/echo":
            body = json.dumps({"proxied": True, "path": self.path}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(404)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        payload = self.rfile.read(length).decode()
        body = json.dumps({"proxied": True, "method": "POST", "body": payload}).encode()
        self.send_response(201)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture
def upstream():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _UpstreamHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _register_active_pack(db, base_url: str, name: str = "autoparts"):
    manifest = parse_manifest(
        {
            "name": name,
            "version": "1.0.0",
            "routes": [{"prefix": f"/{name}", "service": name}],
            "agents": [{"type": "intake"}],
        }
    )
    service = PackService(db)
    service.register(base_url, manifest)
    service.enable(name)


def test_gateway_proxies_get_to_pack(client, db_session, upstream):
    _register_active_pack(db_session, upstream)
    resp = client.get("/api/v1/autoparts/echo")
    assert resp.status_code == 200
    assert resp.json() == {"proxied": True, "path": "/api/v1/echo"}


def test_gateway_proxies_post_with_body(client, db_session, upstream):
    _register_active_pack(db_session, upstream)
    resp = client.post("/api/v1/autoparts/echo", json={"qty": 2})
    assert resp.status_code == 201
    assert resp.json()["method"] == "POST"
    assert '"qty"' in resp.json()["body"]


def test_gateway_unknown_route_returns_404(client, db_session, upstream):
    _register_active_pack(db_session, upstream)
    resp = client.get("/api/v1/unknown-pack/echo")
    assert resp.status_code == 404


def test_gateway_inactive_pack_not_routed(client, db_session, upstream):
    manifest = parse_manifest(
        {
            "name": "autoparts",
            "version": "1.0.0",
            "routes": [{"prefix": "/autoparts", "service": "autoparts"}],
            "agents": [{"type": "intake"}],
        }
    )
    PackService(db_session).register(upstream, manifest)  # installed, not active
    resp = client.get("/api/v1/autoparts/echo")
    assert resp.status_code == 404


def test_gateway_core_reserved_prefix_not_proxied(client, db_session, upstream):
    _register_active_pack(db_session, upstream, name="packs")
    resp = client.get("/api/v1/packs/anything")
    assert resp.status_code == 404
