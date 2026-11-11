"""The client address the app records, across proxy chains and request types."""

from __future__ import annotations

import asyncio
from contextlib import nullcontext
from unittest.mock import MagicMock, patch

import pytest
from a2wsgi import WSGIMiddleware
from flask import Flask, Response, jsonify, request
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Mount, Route, WebSocketRoute
from starlette.testclient import TestClient
from starlette.websockets import WebSocket

from docsgpt.security.client_ip import ClientAddressMiddleware, expand_trusted_proxies

PROXY = "10.0.3.7"  # a Traefik / ingress hop on the container network
CLIENT = "203.0.113.9"
SPOOF = "6.6.6.6"
CF_EDGE = "172.64.1.1"


def _flask_app() -> Flask:
    app = Flask(__name__)

    @app.route("/flask/ip", methods=["GET", "POST", "PUT", "DELETE"])
    def flask_ip():
        return jsonify(ip=request.remote_addr, scheme=request.scheme)

    @app.route("/flask/stream")
    def flask_stream():
        ip = request.remote_addr
        return Response((f"data: {ip}\n\n" for _ in range(2)), mimetype="text/event-stream")

    @app.route("/flask/audit", methods=["POST"])
    def flask_audit():
        from docsgpt.api.audit import record_event

        conn = MagicMock()
        conn.begin_nested.return_value = nullcontext()
        with patch("docsgpt.api.audit.AuthEventsRepository") as repo:
            record_event(conn, "source.deleted", actor="alice")
        return jsonify(ip=repo.return_value.insert.call_args.kwargs["ip"])

    return app


async def _native_ip(req: Request) -> JSONResponse:
    return JSONResponse({"ip": req.client.host, "scheme": req.url.scheme})


async def _native_stream(req: Request) -> StreamingResponse:
    ip = req.client.host

    async def body():
        for _ in range(2):
            yield f"data: {ip}\n\n"
            await asyncio.sleep(0)

    return StreamingResponse(body(), media_type="text/event-stream")


async def _native_ws(ws: WebSocket) -> None:
    await ws.accept()
    await ws.send_json({"ip": ws.client.host})
    await ws.close()


def _client(peer: str, trusted=("private",), cf: bool = False) -> TestClient:
    """The production layout: native routes, then Flask through a2wsgi, under the middleware."""
    app = Starlette(
        routes=[
            Route("/native/ip", _native_ip, methods=["GET", "POST"]),
            Route("/native/stream", _native_stream),
            WebSocketRoute("/native/ws", _native_ws),
            Mount("/", app=WSGIMiddleware(_flask_app())),
        ],
        middleware=[Middleware(ClientAddressMiddleware, trusted_proxies=list(trusted), trust_cf_connecting_ip=cf)],
    )
    return TestClient(app, client=(peer, 50123))


def _all_request_types(client: TestClient, headers: dict) -> dict[str, str]:
    """The IP each kind of request sees."""
    seen = {
        "flask GET": client.get("/flask/ip", headers=headers).json()["ip"],
        "flask POST json": client.post("/flask/ip", json={"a": 1}, headers=headers).json()["ip"],
        "flask POST multipart": client.post(
            "/flask/ip", files={"file": ("a.txt", b"hi")}, headers=headers
        ).json()["ip"],
        "flask PUT": client.put("/flask/ip", content=b"x", headers=headers).json()["ip"],
        "flask DELETE": client.delete("/flask/ip", headers=headers).json()["ip"],
        "flask audit row": client.post("/flask/audit", headers=headers).json()["ip"],
        "native GET": client.get("/native/ip", headers=headers).json()["ip"],
        "native POST": client.post("/native/ip", json={}, headers=headers).json()["ip"],
    }
    with client.stream("GET", "/flask/stream", headers=headers) as r:
        seen["flask SSE"] = r.read().decode().split("\n")[0].removeprefix("data: ")
    with client.stream("GET", "/native/stream", headers=headers) as r:
        seen["native SSE"] = r.read().decode().split("\n")[0].removeprefix("data: ")
    with client.websocket_connect("/native/ws", headers=headers) as ws:
        seen["websocket"] = ws.receive_json()["ip"]
    return seen


def _assert_every_type(client: TestClient, headers: dict, expected: str) -> None:
    seen = _all_request_types(client, headers)
    assert seen == {kind: expected for kind in seen}


@pytest.mark.unit
class TestProxyChains:
    def test_behind_private_proxy_takes_forwarded_client(self):
        _assert_every_type(_client(PROXY), {"X-Forwarded-For": CLIENT}, CLIENT)

    def test_spoofed_leftmost_entries_are_ignored(self):
        _assert_every_type(_client(PROXY), {"X-Forwarded-For": f"{SPOOF}, {CLIENT}, 10.0.0.2"}, CLIENT)

    def test_split_forwarded_for_headers_are_joined(self):
        client = _client(PROXY)
        r = client.get("/flask/ip", headers=[("X-Forwarded-For", SPOOF), ("X-Forwarded-For", CLIENT)])
        assert r.json()["ip"] == CLIENT

    def test_public_peer_cannot_forward(self):
        _assert_every_type(_client("198.51.100.20"), {"X-Forwarded-For": SPOOF}, "198.51.100.20")

    def test_no_header_keeps_peer(self):
        _assert_every_type(_client(PROXY), {}, PROXY)

    def test_ipv6_client_with_port(self):
        r = _client(PROXY).get("/flask/ip", headers={"X-Forwarded-For": "[2001:db8::5]:4431"})
        assert r.json()["ip"] == "2001:db8::5"

    def test_none_trusts_nobody(self):
        _assert_every_type(_client(PROXY, trusted=()), {"X-Forwarded-For": CLIENT}, PROXY)

    def test_star_takes_leftmost(self):
        r = _client("198.51.100.20", trusted=("*",)).get("/flask/ip", headers={"X-Forwarded-For": f"{SPOOF}, {CLIENT}"})
        assert r.json()["ip"] == SPOOF

    def test_forwarded_proto_sets_scheme(self):
        headers = {"X-Forwarded-For": CLIENT, "X-Forwarded-Proto": "https"}
        client = _client(PROXY)
        assert client.get("/flask/ip", headers=headers).json()["scheme"] == "https"
        assert client.get("/native/ip", headers=headers).json()["scheme"] == "https"

    def test_forwarded_proto_from_untrusted_peer_ignored(self):
        r = _client("198.51.100.20").get("/flask/ip", headers={"X-Forwarded-Proto": "https"})
        assert r.json()["scheme"] == "http"


@pytest.mark.unit
class TestCloudflare:
    # Cloudflare appends the visitor to any X-Forwarded-For it received, then the
    # private proxy appends the Cloudflare edge that connected to it.
    CHAIN = {"X-Forwarded-For": f"{SPOOF}, {CLIENT}, {CF_EDGE}", "CF-Connecting-IP": CLIENT}

    def test_private_only_records_cloudflare_edge(self):
        _assert_every_type(_client(PROXY), self.CHAIN, CF_EDGE)

    def test_cloudflare_ranges_walk_past_the_edge(self):
        _assert_every_type(_client(PROXY, trusted=("private", "cloudflare")), self.CHAIN, CLIENT)

    def test_cf_header_through_private_proxy(self):
        headers = {"X-Forwarded-For": f"{SPOOF}, {CF_EDGE}", "CF-Connecting-IP": CLIENT}
        _assert_every_type(_client(PROXY, cf=True), headers, CLIENT)

    def test_cf_header_with_cloudflare_as_direct_peer(self):
        _assert_every_type(_client(CF_EDGE, cf=True), {"CF-Connecting-IP": CLIENT}, CLIENT)

    def test_cf_header_ignored_when_request_bypasses_cloudflare(self):
        headers = {"X-Forwarded-For": "198.51.100.7", "CF-Connecting-IP": SPOOF}
        _assert_every_type(_client(PROXY, cf=True), headers, "198.51.100.7")

    def test_cf_header_ignored_when_off(self):
        _assert_every_type(_client(CF_EDGE), {"CF-Connecting-IP": CLIENT}, CF_EDGE)

    def test_malformed_or_repeated_cf_header_ignored(self):
        client = _client(CF_EDGE, cf=True)
        assert client.get("/flask/ip", headers={"CF-Connecting-IP": "not-an-ip"}).json()["ip"] == CF_EDGE
        repeated = [("CF-Connecting-IP", CLIENT), ("CF-Connecting-IP", SPOOF)]
        assert client.get("/flask/ip", headers=repeated).json()["ip"] == CF_EDGE

    def test_ipv6_cf_edge_and_client(self):
        r = _client("2606:4700::1", cf=True).get("/flask/ip", headers={"CF-Connecting-IP": "2001:db8::9"})
        assert r.json()["ip"] == "2001:db8::9"


@pytest.mark.unit
class TestExpand:
    def test_keywords_expand(self):
        nets = expand_trusted_proxies(["private", "cloudflare", "192.0.2.1"])
        assert "10.0.0.0/8" in nets and "173.245.48.0/20" in nets and "192.0.2.1/32" in nets

    def test_duplicates_and_blanks_dropped(self):
        assert expand_trusted_proxies(["10.0.0.0/8", " ", "10.0.0.5/8"]) == ["10.0.0.0/8"]

    def test_star_alone(self):
        assert expand_trusted_proxies(["*"]) == ["*"]
        with pytest.raises(ValueError):
            expand_trusted_proxies(["*", "private"])

    def test_bad_entry_rejected(self):
        with pytest.raises(ValueError, match="bogus"):
            expand_trusted_proxies(["bogus"])

    def test_settings_parse(self, monkeypatch):
        from docsgpt.core.settings.server import ServerSettings

        monkeypatch.setenv("TRUSTED_PROXIES", "private,cloudflare,10.1.0.0/16")
        assert ServerSettings().TRUSTED_PROXIES == ["private", "cloudflare", "10.1.0.0/16"]
        monkeypatch.setenv("TRUSTED_PROXIES", "none")
        assert ServerSettings().TRUSTED_PROXIES == []
        monkeypatch.delenv("TRUSTED_PROXIES")
        assert ServerSettings().TRUSTED_PROXIES == ["private"]


@pytest.mark.unit
def test_production_asgi_app_resolves_client():
    """The real asgi_app carries the middleware with the default settings."""
    from docsgpt.asgi import asgi_app

    with TestClient(asgi_app, client=(PROXY, 50123)) as client:
        r = client.get("/api/health", headers={"X-Forwarded-For": f"{SPOOF}, {CLIENT}"})
    assert r.status_code == 200
    assert any(m.cls is ClientAddressMiddleware for m in asgi_app.user_middleware)
