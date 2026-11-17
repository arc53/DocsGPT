"""Which custom models a chat may run on, and in whose account they resolve.

A team chat without an agent offers the instance's models and the team's own: a model asked for there resolves
in the team's account (``model_user_id`` is the team's principal). A person's own model is not offered in a
team chat: 400 ``custom_model_personal_only``. A Personal chat is unchanged. An agent always runs on its
owner's models, so a team agent shared into another team runs on the owning team's model, and a headless run of
a team agent does too. Real repositories and the real model registry on ``pg_conn``.
"""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask, request

from docsgpt.storage.db.repositories.agents import AgentsRepository
from docsgpt.storage.db.repositories.team_item_shares import TeamItemSharesRepository
from docsgpt.storage.db.repositories.user_custom_models import UserCustomModelsRepository
from docsgpt.workspaces.context import WORKSPACE_HEADER
from tests.workspaces.move_support import team


@pytest.fixture(autouse=True)
def _registry():
    from docsgpt.core.model_registry import ModelRegistry

    ModelRegistry.reset()
    yield
    ModelRegistry.reset()


@pytest.fixture
def use_conn(monkeypatch, pg_conn):
    @contextmanager
    def _yield():
        yield pg_conn

    for module in (
        "docsgpt.api.answer.services.stream_processor",
        "docsgpt.api.answer.services.conversation_service",
        "docsgpt.agents.tool_executor",
        "docsgpt.agents.headless_runner",
        # The model registry loads each account's custom models through the session module.
        "docsgpt.storage.db.session",
    ):
        monkeypatch.setattr(f"{module}.db_readonly", _yield, raising=False)
        monkeypatch.setattr(f"{module}.db_session", _yield, raising=False)
    return pg_conn


def _model(conn, owner: str, name: str) -> str:
    return str(UserCustomModelsRepository(conn).create(
        owner, "llama-3", name, "https://m.example/v1", f"sk-{name}", created_by="adam" if owner.startswith(
            "__team__") else None,
    )["id"])


@pytest.fixture
def world(use_conn):
    """Ops (alice owner, adam admin, eddie editor, vera viewer) with a team model, Dev (dora, rita) with its own;
    vera has a model of her own."""
    conn = use_conn
    ops, ops_p = team(conn)
    dev, dev_p = team(conn, owner="dora", name="Dev", members=(("rita", "team_viewer"),))
    return {
        "ops": ops, "ops_p": ops_p, "dev": dev, "dev_p": dev_p,
        "ops_model": _model(conn, ops_p, "Ops Llama"),
        "dev_model": _model(conn, dev_p, "Dev Llama"),
        "vera_model": _model(conn, "vera", "Vera Llama"),
    }


@contextmanager
def _request(workspace=None, caller="vera"):
    headers = {WORKSPACE_HEADER: workspace} if workspace is not None else {}
    with Flask(__name__).test_request_context("/stream", method="POST", headers=headers):
        request.decoded_token = {"sub": caller}
        yield


def _chat(caller="vera", workspace=None, **data):
    from docsgpt.api.answer.services.stream_processor import StreamProcessor

    with _request(workspace, caller):
        proc = StreamProcessor({"question": "q", **data}, {"sub": caller})
        proc._configure_agent()
        proc._validate_and_set_model()
    return proc


class TestTeamChatWithoutAnAgent:
    def test_runs_on_the_teams_model_in_the_teams_account(self, world):
        proc = _chat(workspace=world["ops"], model_id=world["ops_model"])
        assert proc.workspace_team_id == world["ops"]
        assert proc.model_id == world["ops_model"]
        assert proc.model_user_id == world["ops_p"]

    def test_an_instance_model_resolves_in_the_teams_account_too(self, world):
        proc = _chat(workspace=world["ops"], model_id="docsgpt-local")
        assert proc.model_id == "docsgpt-local"
        assert proc.model_user_id == world["ops_p"]

    def test_the_callers_own_model_is_refused(self, world):
        from docsgpt.api.answer.services.stream_processor import ChatWorkspaceError

        with pytest.raises(ChatWorkspaceError, match="can't be used in a team chat") as refused:
            _chat(workspace=world["ops"], model_id=world["vera_model"])
        assert (refused.value.status, refused.value.code) == (400, "custom_model_personal_only")

    def test_another_teams_model_is_refused(self, world):
        with pytest.raises(ValueError, match="Invalid model_id"):
            _chat(workspace=world["ops"], model_id=world["dev_model"])

    def test_no_model_asked_for_runs_on_the_default(self, world):
        proc = _chat(workspace=world["ops"])
        assert proc.model_user_id is None


class TestPersonalChat:
    def test_runs_on_the_callers_own_model_in_their_account(self, world):
        proc = _chat(model_id=world["vera_model"])
        assert proc.workspace_team_id is None
        assert proc.model_id == world["vera_model"]
        assert proc.model_user_id == "vera"

    def test_a_teams_model_is_refused(self, world):
        with pytest.raises(ValueError, match="Invalid model_id"):
            _chat(model_id=world["ops_model"])


class TestAgentChats:
    def test_a_team_agent_shared_into_another_team_runs_on_the_owning_teams_model(self, use_conn, world):
        agent = str(AgentsRepository(use_conn).create(
            world["ops_p"], "Ops helper", "published", key="ops-model-key", default_model_id=world["ops_model"],
            created_by="alice",
        )["id"])
        TeamItemSharesRepository(use_conn).share(world["ops"], world["dev"], "agent", agent, "adam")

        proc = _chat(caller="rita", workspace=world["dev"], agent_id=agent, model_id=world["dev_model"])

        assert proc.workspace_team_id == world["dev"]
        assert proc.model_id == world["ops_model"]
        assert proc.model_user_id == world["ops_p"]

    @pytest.mark.parametrize("model_key, runs_on", [("ops_model", "ops_model"), ("vera_model", None)])
    def test_a_headless_run_of_a_team_agent_runs_on_the_teams_model_only(self, monkeypatch, world, model_key, runs_on):
        from docsgpt.agents import headless_runner as hr

        created: dict = {}
        agent = MagicMock(name="agent")
        agent.gen.return_value = iter([{"answer": "ok"}])
        agent.llm.token_usage = {}

        def _create_agent(cls, type_, *args, **kwargs):
            created.update(kwargs)
            return agent

        monkeypatch.setattr(hr, "get_prompt", lambda _pid: "system prompt")
        monkeypatch.setattr(hr.RetrieverCreator, "create_retriever",
                            classmethod(lambda cls, *a, **kw: MagicMock(search=MagicMock(return_value=[]))))
        monkeypatch.setattr(hr, "ToolExecutor", lambda *a, **kw: MagicMock(headless_denials=[]))
        monkeypatch.setattr(hr.AgentCreator, "create_agent", classmethod(_create_agent))
        monkeypatch.setattr(hr.QuotaService, "check", lambda *a, **kw: None)
        config = {"user_id": world["ops_p"], "id": "agent-1", "default_model_id": world[model_key],
                  "agent_type": "classic"}
        with patch("docsgpt.core.model_utils.get_api_key_for_provider", return_value="k"), \
                patch("docsgpt.core.model_utils.get_default_model_id", return_value="docsgpt-local"), \
                patch("docsgpt.utils.calculate_doc_token_budget", return_value=1000):
            hr.run_agent_headless(config, "do the thing", payer="eddie")

        # The run's model resolves as the team (its token's ``sub``); a person's model falls back to the default.
        assert created["model_id"] == (world[runs_on] if runs_on else "docsgpt-local")
        assert created["decoded_token"] == {"sub": world["ops_p"]}
