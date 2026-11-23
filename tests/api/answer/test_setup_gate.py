"""A turn's limits are checked before its setup reaches a model, and that setup is billed like the turn.

Setting a turn up can call a model before the answer starts: history compression, the query rephrase, the source
prescreen. The routes check the limits as soon as the caller and agent are known (``StreamProcessor.build_agent``
calls the route's ``setup_gate``), so a refused turn spends nothing, and the rest of the setup runs in the same
billing the stream opens: its payer, run kind, workspace and per-call limits.
"""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import patch

import pytest
from flask import Flask, make_response, request

from docsgpt.api.answer.routes.base import BaseAnswerResource, UsageRefused
from docsgpt.api.answer.services.stream_processor import StreamProcessor
from docsgpt.quotas.payer import current_run_billing
from docsgpt.quotas.service import NoPayerError

BASE = "docsgpt.api.answer.routes.base"


class _SetupRan(Exception):
    """Stops a build once setup reached the step that can call a model."""


def _configured(agent_config, sub, *, agent_id=None, team_id=None):
    """A ``_configure_agent`` stand-in: the caller and agent as the real one resolves them."""

    def _configure(self):
        self.agent_config.update(agent_config)
        self.decoded_token = {"sub": sub}
        self.agent_id = agent_id
        self.workspace_team_id = team_id

    return _configure


def _refusal():
    return make_response({"success": False, "error_code": "quota-exceeded"}, 429)


@pytest.mark.unit
class TestARefusedTurnSpendsNothing:
    @pytest.mark.parametrize("route", ["/stream", "/api/answer"])
    def test_setup_never_reaches_a_model(self, route):
        from docsgpt.api.answer.routes.answer import AnswerResource
        from docsgpt.api.answer.routes.stream import StreamResource

        resource = AnswerResource if route == "/api/answer" else StreamResource
        setup = []
        with patch.object(StreamProcessor, "_configure_agent", _configured({}, "dana")), patch.object(
            StreamProcessor, "_validate_and_set_model", lambda self: setup.append("ran")
        ), patch.object(BaseAnswerResource, "check_usage", lambda *a, **kw: _refusal()):
            with Flask(__name__).test_request_context(route, method="POST", json={"question": "hi"}):
                request.decoded_token = {"sub": "dana"}
                response = resource().post()

        assert response.status_code == 429
        assert setup == []

    def test_v1_setup_never_reaches_a_model(self, pg_conn):
        from docsgpt.api.v1.routes import _V1AnswerHelper, v1_bp
        from docsgpt.storage.db.repositories.agents import AgentsRepository

        AgentsRepository(pg_conn).create("lena", "Desk", "published", key="setup-gate-key")
        app = Flask(__name__)
        app.register_blueprint(v1_bp)
        setup = []

        @contextmanager
        def _db():
            yield pg_conn

        with patch("docsgpt.api.v1.routes.db_readonly", _db), patch.object(
            StreamProcessor, "_configure_agent", _configured({"external_api_caller": True}, "lena")
        ), patch.object(StreamProcessor, "_validate_and_set_model", lambda self: setup.append("ran")), patch.object(
            _V1AnswerHelper, "check_usage", lambda *a, **kw: _refusal()
        ):
            response = app.test_client().post(
                "/v1/chat/completions",
                headers={"Authorization": "Bearer setup-gate-key"},
                json={"messages": [{"role": "user", "content": "hi"}]},
            )

        assert response.status_code == 429
        assert setup == []


@pytest.mark.unit
class TestSetupIsBilledLikeTheTurn:
    def _build(self, configure):
        """Build up to the setup step that can call a model, returning the billing it ran in."""
        seen = {}

        def _initialize(self):
            seen["billing"] = current_run_billing()
            raise _SetupRan()

        processor = StreamProcessor({"question": "hi"}, {"sub": "x"})
        processor.setup_gate = BaseAnswerResource().setup_gate
        with patch.object(StreamProcessor, "_configure_agent", configure), patch.object(
            StreamProcessor, "_validate_and_set_model", _initialize
        ), patch.object(BaseAnswerResource, "check_usage", lambda *a, **kw: None), patch(
            f"{BASE}.RunLimits.start", return_value="limits"
        ), pytest.raises(_SetupRan):
            processor.build_agent("hi")
        return processor, seen["billing"]

    def test_a_chat_bills_the_person_in_its_workspace(self):
        processor, billing = self._build(_configured({}, "dana", team_id="team-1"))

        assert (billing.payer, billing.kind, billing.team_id) == ("dana", "chat", "team-1")
        assert billing.request_id == processor.request_id
        assert billing.limits == "limits"
        assert processor.setup_gate_passed is True

    def test_key_traffic_bills_the_publisher_in_the_agents_team(self):
        configure = _configured(
            {"external_api_caller": True, "user_api_key": "k"}, "team:principal", agent_id="agent-1"
        )
        with patch(f"{BASE}.agent_payer_and_team", return_value=("lena", "team-9")):
            _, billing = self._build(configure)

        assert (billing.payer, billing.kind, billing.team_id) == ("lena", "published", "team-9")

    def test_nobody_to_pay_is_refused_before_setup(self):
        setup = []
        processor = StreamProcessor({"question": "hi"}, {"sub": "x"})
        processor.setup_gate = BaseAnswerResource().setup_gate
        with patch.object(StreamProcessor, "_configure_agent", _configured({}, "dana")), patch.object(
            StreamProcessor, "_validate_and_set_model", lambda self: setup.append("ran")
        ), patch.object(BaseAnswerResource, "check_usage", lambda *a, **kw: None), patch(
            f"{BASE}.RunLimits.start", side_effect=NoPayerError("team:principal")
        ), Flask(__name__).app_context(), pytest.raises(UsageRefused) as refused:
            processor.build_agent("hi")

        assert refused.value.response.status_code == 403
        assert setup == []
