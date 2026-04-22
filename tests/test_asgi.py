"""Smoke tests for application/asgi.py.

The goal isn't to re-test Flask or FastMCP internals — it's to catch
regressions in the wiring: mounts resolve, CORS headers emit, lifespan
runs (without it, the /mcp session manager raises "Task group is not
initialized"), routing to ``/`` vs ``/mcp`` doesn't cross paths.

Uses ``starlette.testclient.TestClient`` because it boots the ASGI app
end-to-end and handles the lifespan protocol automatically — ``httpx``
alone does not run lifespan events, which would mask the exact kind of
misconfiguration this test suite exists to catch.
"""

import pytest


@pytest.mark.unit
def test_asgi_app_imports():
    from application.asgi import asgi_app

    assert asgi_app is not None


@pytest.mark.unit
def test_flask_route_served_through_starlette_mount():
    """GET /api/health should reach the Flask app via a2wsgi and return 200."""
    from starlette.testclient import TestClient

    from application.asgi import asgi_app

    with TestClient(asgi_app) as client:
        r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


@pytest.mark.unit
def test_mcp_endpoint_mounted_and_lifespan_runs():
    """/mcp must be reachable AND the FastMCP session manager must start.

    Without ``lifespan=mcp_app.lifespan`` on the outer Starlette app,
    every /mcp request raises ``RuntimeError: Task group is not
    initialized``. Hitting the endpoint under a real lifespan-aware
    client catches that.
    """
    from starlette.testclient import TestClient

    from application.asgi import asgi_app

    with TestClient(asgi_app) as client:
        # Minimal MCP initialize request. Doesn't need to succeed — we
        # just need a non-404, non-500-with-RuntimeError response to
        # confirm the mount + lifespan are both wired.
        r = client.post(
            "/mcp/",
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
            },
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "pytest", "version": "0"},
                },
            },
        )
    assert r.status_code != 404, f"/mcp mount unreachable: {r.status_code}"
    # A successful initialize returns 200 with a Mcp-Session-Id header.
    assert r.status_code == 200
    assert "mcp-session-id" in {k.lower() for k in r.headers.keys()}


@pytest.mark.unit
def test_cors_headers_on_flask_route():
    """CORS middleware should emit allow-origin on actual (non-preflight) requests.

    ``allow_origins=["*"]`` → header value is literal ``*`` (not an echo).
    """
    from starlette.testclient import TestClient

    from application.asgi import asgi_app

    with TestClient(asgi_app) as client:
        r = client.get("/api/health", headers={"Origin": "http://example.com"})
    assert r.status_code == 200
    assert r.headers.get("access-control-allow-origin") == "*"


@pytest.mark.unit
def test_cors_preflight_on_flask_route():
    """OPTIONS preflight on a Flask route should be handled by Starlette CORSMiddleware."""
    from starlette.testclient import TestClient

    from application.asgi import asgi_app

    with TestClient(asgi_app) as client:
        r = client.options(
            "/api/health",
            headers={
                "Origin": "http://example.com",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "Content-Type",
            },
        )
    assert r.status_code in (200, 204)
    assert r.headers.get("access-control-allow-origin") == "*"
    assert "GET" in r.headers.get("access-control-allow-methods", "")


@pytest.mark.unit
def test_cors_preflight_on_mcp_route():
    """Browser clients hitting /mcp should also get CORS preflight handled."""
    from starlette.testclient import TestClient

    from application.asgi import asgi_app

    with TestClient(asgi_app) as client:
        r = client.options(
            "/mcp/",
            headers={
                "Origin": "http://example.com",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "Authorization, Content-Type",
            },
        )
    assert r.status_code in (200, 204)
    assert r.headers.get("access-control-allow-origin") == "*"
