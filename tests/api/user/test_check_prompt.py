"""POST /api/check_prompt: the prompt editor's model-free checks."""

from __future__ import annotations

import pytest
from flask import Flask


@pytest.fixture
def app():
    return Flask(__name__)


def _post(app, body, token={"sub": "alice"}):
    from docsgpt.api.user.prompts.routes import CheckPrompt

    with app.test_request_context("/api/check_prompt", method="POST", json=body):
        from flask import request

        request.decoded_token = token
        return CheckPrompt().post()


@pytest.mark.unit
class TestCheckPrompt:
    def test_it_returns_the_checks(self, app):
        resp = _post(app, {"content": "You help Northwind.\nEmail [support email]."})
        assert resp.status_code == 200
        assert resp.json == {"checks": [{"code": "placeholder", "text": "[support email]", "line": 2}]}

    def test_a_clean_prompt_has_none(self, app):
        assert _post(app, {"content": "You help Northwind customers."}).json == {"checks": []}

    def test_it_needs_a_session(self, app):
        assert _post(app, {"content": "x"}, token=None).status_code == 401

    @pytest.mark.parametrize("body", [{}, {"content": 5}, {"content": None}, ["x"]])
    def test_content_must_be_text(self, app, body):
        assert _post(app, body).status_code == 400

    def test_empty_text_has_no_checks(self, app):
        assert _post(app, {"content": ""}).json == {"checks": []}

    def test_content_over_the_read_cap_is_refused(self, app):
        from docsgpt.drafter.prompt_recipe import READ_MAX

        assert _post(app, {"content": "x" * READ_MAX}).status_code == 200
        assert _post(app, {"content": "x" * (READ_MAX + 1)}).status_code == 400

    def test_it_runs_with_the_drafter_off(self, app, monkeypatch):
        from docsgpt.core.settings import settings

        monkeypatch.setattr(settings, "DRAFTER_ENABLED", False, raising=False)
        assert _post(app, {"content": "TODO"}).status_code == 200

    def test_past_the_minute_limit_it_is_a_429(self, app, monkeypatch):
        import docsgpt.monitors.triggers as triggers

        seen = []

        def limited(scope, user, limit):
            seen.append((scope, user, limit))
            return True

        monkeypatch.setattr(triggers, "rate_limited", limited)
        resp = _post(app, {"content": "TODO"})
        assert resp.status_code == 429
        from docsgpt.api.user.prompts.routes import CHECK_PROMPT_RATE_PER_MINUTE

        assert seen == [("check_prompt", "alice", CHECK_PROMPT_RATE_PER_MINUTE)]
