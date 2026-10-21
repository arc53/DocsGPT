"""The admin-only decision model status: the diagnostics kept off the public /api/config."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest


@pytest.fixture
def client():
    from docsgpt.app import app as flask_app

    flask_app.config["TESTING"] = True
    return flask_app.test_client()


@pytest.mark.unit
class TestAdminDecisions:
    def test_non_admin_forbidden(self, client):
        with patch("docsgpt.app.handle_auth", return_value={"sub": "u"}), patch(
            "docsgpt.app.resolve_roles", return_value=["user"]
        ):
            assert client.get("/api/admin/decisions").status_code == 403

    def test_unauthenticated(self, client):
        with patch("docsgpt.app.handle_auth", return_value=None):
            assert client.get("/api/admin/decisions").status_code == 401

    def test_reports_the_full_status_without_loading(self, client, monkeypatch):
        from docsgpt import decisions
        from docsgpt.core.settings import settings

        # Every setting the status reads, pinned to its default, so a developer's .env cannot change the answer.
        for name, value in {
            "DECISION_MODE": None,
            "DECISION_MODEL": None,
            "DECISION_BASE_URL": None,
            "DECISION_INJECTION_ENABLED": False,
            "DECISION_ANALYTICS_ENABLED": False,
            "DECISION_RELEVANCE_ENABLED": False,
            "DECISION_BACKGROUND_TIMEOUT": 120.0,
            "DECISION_RELEVANCE_TIMEOUT": 2.0,
        }.items():
            monkeypatch.setattr(settings, name, value)
        with patch("docsgpt.app.handle_auth", return_value={"sub": "admin1"}), patch(
            "docsgpt.app.resolve_roles", return_value=["admin", "user"]
        ):
            resp = client.get("/api/admin/decisions")
        assert resp.status_code == 200
        assert json.loads(resp.data) == {
            "success": True,
            "available": True,
            "mode": "local",
            "status": "idle",
            "reason": None,
            "model": "arc53/arc-decide-0.4b-v0.2",
            "version": "arc53/arc-decide-0.4b-v0.2/p78cfb276f93a/cc3bc72ff6907",
            "runtime": "onnx-int8",
            "speed": None,
            "features": {
                "injection_input": {
                    "mode": "off", "effective": "off", "predicted_s": None, "budget_s": 2.0, "reason": "configured",
                },
                "analytics_turn": {
                    "mode": "off", "effective": "off", "predicted_s": None, "budget_s": 120.0, "reason": "configured",
                },
                "rag_rerank": {
                    "mode": "off", "effective": "off", "predicted_s": None, "budget_s": 2.0, "reason": "configured",
                },
            },
        }
        assert decisions.get_decider()._backend is None
