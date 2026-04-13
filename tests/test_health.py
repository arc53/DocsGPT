"""Unit tests for /api/health, /api/ready, and application.healthcheck CLI."""

import json
from unittest.mock import patch

import pytest
from application.core.service_checks import CheckResult
from flask import Flask, jsonify


def _register_health_routes(app: Flask) -> None:
    """Register only health/ready routes (mirrors application.app additions)."""
    from application.core.service_checks import required_service_checks, summarize_checks

    @app.route("/api/health")
    def healthcheck():
        return jsonify({"status": "ok", "service": "backend"})

    @app.route("/api/ready")
    def readiness_check():
        checks = required_service_checks()
        all_ok, payload = summarize_checks(checks)
        status_code = 200 if all_ok else 503
        return jsonify({"status": "ready" if all_ok else "degraded", "checks": payload}), status_code


@pytest.mark.unit
def test_api_health_returns_200_and_body():
    """GET /api/health returns 200 with status ok and service backend."""
    app = Flask(__name__)
    _register_health_routes(app)
    client = app.test_client()
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.get_json()
    assert data == {"status": "ok", "service": "backend"}


@pytest.mark.unit
@patch("application.core.service_checks.required_service_checks")
@patch("application.core.service_checks.summarize_checks")
def test_api_ready_returns_200_when_healthy(mock_summarize, mock_required):
    """GET /api/ready returns 200 and status ready when all checks pass."""
    mock_required.return_value = {
        "redis": CheckResult(ok=True, detail="ok"),
        "mongo": CheckResult(ok=True, detail="ok"),
    }
    mock_summarize.return_value = (
        True,
        {"redis": {"ok": True, "detail": "ok"}, "mongo": {"ok": True, "detail": "ok"}},
    )
    app = Flask(__name__)
    _register_health_routes(app)
    client = app.test_client()
    response = client.get("/api/ready")
    assert response.status_code == 200
    data = response.get_json()
    assert data["status"] == "ready"
    assert "checks" in data


@pytest.mark.unit
@patch("application.core.service_checks.required_service_checks")
@patch("application.core.service_checks.summarize_checks")
def test_api_ready_returns_503_when_degraded(mock_summarize, mock_required):
    """GET /api/ready returns 503 and status degraded when a check fails."""
    mock_required.return_value = {
        "redis": CheckResult(ok=True, detail="ok"),
        "mongo": CheckResult(ok=False, detail="connection failed"),
    }
    mock_summarize.return_value = (
        False,
        {"redis": {"ok": True, "detail": "ok"}, "mongo": {"ok": False, "detail": "connection failed"}},
    )
    app = Flask(__name__)
    _register_health_routes(app)
    client = app.test_client()
    response = client.get("/api/ready")
    assert response.status_code == 503
    data = response.get_json()
    assert data["status"] == "degraded"
    assert data["checks"]["mongo"]["ok"] is False


@pytest.mark.unit
@patch("application.healthcheck.required_service_checks")
@patch("application.healthcheck.summarize_checks")
def test_healthcheck_cli_dependencies_healthy(mock_summarize, mock_required, capsys):
    """healthcheck --target dependencies exits 0 and prints JSON when checks pass."""
    mock_required.return_value = {
        "redis": CheckResult(ok=True, detail="ok"),
        "mongo": CheckResult(ok=True, detail="ok"),
    }
    mock_summarize.return_value = (
        True,
        {"redis": {"ok": True, "detail": "ok"}, "mongo": {"ok": True, "detail": "ok"}},
    )
    from application.healthcheck import main

    import sys

    old = sys.argv
    try:
        sys.argv = ["healthcheck", "--target", "dependencies"]
        exit_code = main()
        assert exit_code == 0
        out = capsys.readouterr().out
    finally:
        sys.argv = old
    data = json.loads(out)
    assert data["target"] == "dependencies"
    assert data["healthy"] is True
    assert "checks" in data


@pytest.mark.unit
@patch("application.healthcheck.required_service_checks")
@patch("application.healthcheck.summarize_checks")
def test_healthcheck_cli_dependencies_unhealthy(mock_summarize, mock_required, capsys):
    """healthcheck --target dependencies exits 1 when a check fails."""
    mock_required.return_value = {
        "redis": CheckResult(ok=False, detail="connection failed"),
        "mongo": CheckResult(ok=True, detail="ok"),
    }
    mock_summarize.return_value = (
        False,
        {"redis": {"ok": False, "detail": "connection failed"}, "mongo": {"ok": True, "detail": "ok"}},
    )
    from application.healthcheck import main

    import sys

    old = sys.argv
    try:
        sys.argv = ["healthcheck", "--target", "dependencies"]
        exit_code = main()
        assert exit_code == 1
        out = capsys.readouterr().out
    finally:
        sys.argv = old
    data = json.loads(out)
    assert data["healthy"] is False


@pytest.mark.unit
@patch("application.healthcheck._check_backend_endpoint")
def test_healthcheck_cli_backend_healthy(mock_check):
    """healthcheck --target backend exits 0 when backend URL returns 200."""
    mock_check.return_value = True
    from application.healthcheck import main

    import sys

    old = sys.argv
    try:
        sys.argv = ["healthcheck", "--target", "backend"]
        exit_code = main()
        assert exit_code == 0
    finally:
        sys.argv = old


@pytest.mark.unit
@patch("application.healthcheck._check_backend_endpoint")
def test_healthcheck_cli_backend_unhealthy(mock_check):
    """healthcheck --target backend exits 1 when backend URL fails."""
    mock_check.return_value = False
    from application.healthcheck import main

    import sys

    old = sys.argv
    try:
        sys.argv = ["healthcheck", "--target", "backend"]
        exit_code = main()
        assert exit_code == 1
    finally:
        sys.argv = old
