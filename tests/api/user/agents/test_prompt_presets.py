"""Agents keep the ``creative`` and ``strict`` prompt presets.

The presets have no ``prompts`` row, so ``agents.prompt_id`` (a UUID foreign
key) can't hold them: the repository stores them in ``agents.prompt_preset``
and reads them back as ``prompt_id``. These tests cover the routes, the
export/import file and the run paths that read an agent's prompt.
"""

from contextlib import contextmanager
from unittest.mock import patch

import pytest
from flask import Flask
from sqlalchemy import text

from docsgpt.storage.db.repositories.agents import AgentsRepository
from docsgpt.storage.db.repositories.prompts import PromptsRepository


@pytest.fixture
def app():
    return Flask(__name__)


@contextmanager
def _patch_db(conn):
    @contextmanager
    def _yield():
        yield conn

    with patch("docsgpt.api.user.agents.routes.db_session", _yield), patch(
        "docsgpt.api.user.agents.routes.db_readonly", _yield
    ):
        yield


def _stored(conn, agent_id) -> tuple:
    return tuple(
        conn.execute(
            text("SELECT CAST(prompt_id AS text), prompt_preset FROM agents WHERE id = CAST(:id AS uuid)"),
            {"id": str(agent_id)},
        ).one()
    )


def _create(app, conn, user, **body):
    from docsgpt.api.user.agents.routes import CreateAgent

    payload = {"name": "Preset Bot", "description": "d", "agent_type": "classic", "status": "draft", **body}
    with _patch_db(conn), app.test_request_context("/api/create_agent", method="POST", json=payload):
        from flask import request

        request.decoded_token = {"sub": user}
        return CreateAgent().post()


def _update(app, conn, user, agent_id, **body):
    from docsgpt.api.user.agents.routes import UpdateAgent

    payload = {"name": "n", "description": "d", "status": "draft", **body}
    with _patch_db(conn), app.test_request_context(f"/api/update_agent/{agent_id}", method="PUT", json=payload):
        from flask import request

        request.decoded_token = {"sub": user}
        return UpdateAgent().put(str(agent_id))


def _status(response) -> int:
    return response[1] if isinstance(response, tuple) else response.status_code


class TestCreateRoute:
    @pytest.mark.parametrize("preset", ["creative", "strict"])
    def test_keeps_the_preset(self, app, pg_conn, preset):
        user = f"u-create-{preset}"
        response = _create(app, pg_conn, user, prompt_id=preset)
        assert _status(response) == 201, response.json
        agent = AgentsRepository(pg_conn).list_for_user(user)[0]
        assert agent["prompt_id"] == preset
        assert _stored(pg_conn, agent["id"]) == (None, preset)

    def test_published_agent_keeps_the_preset(self, app, pg_conn):
        user = "u-create-pub-preset"
        response = _create(
            app, pg_conn, user, status="published", chunks="2", retriever="classic", prompt_id="strict"
        )
        assert _status(response) == 201, response.json
        assert AgentsRepository(pg_conn).list_for_user(user)[0]["prompt_id"] == "strict"

    def test_default_and_a_prompt_row(self, app, pg_conn):
        user = "u-create-default-row"
        prompt = PromptsRepository(pg_conn).create(user, "p", "c")
        assert _status(_create(app, pg_conn, user, name="a", prompt_id="default")) == 201
        assert _status(_create(app, pg_conn, user, name="b", prompt_id=str(prompt["id"]))) == 201
        by_name = {a["name"]: a for a in AgentsRepository(pg_conn).list_for_user(user)}
        assert by_name["a"]["prompt_id"] is None
        assert by_name["b"]["prompt_id"] == str(prompt["id"])

    def test_rejects_garbage(self, app, pg_conn):
        user = "u-create-garbage"
        response = _create(app, pg_conn, user, prompt_id="not-a-uuid")
        assert _status(response) == 400
        assert AgentsRepository(pg_conn).list_for_user(user) == []


class TestUpdateRoute:
    @pytest.mark.parametrize("preset", ["creative", "strict"])
    def test_sets_the_preset(self, app, pg_conn, preset):
        user = f"u-update-{preset}"
        agent = AgentsRepository(pg_conn).create(user, "a", "draft", description="d")
        response = _update(app, pg_conn, user, agent["id"], prompt_id=preset)
        assert _status(response) == 200, response.json
        assert AgentsRepository(pg_conn).get(str(agent["id"]), user)["prompt_id"] == preset
        assert _stored(pg_conn, agent["id"]) == (None, preset)

    def test_switches_from_a_prompt_row_to_a_preset_and_back(self, app, pg_conn):
        user = "u-update-switch"
        prompt = PromptsRepository(pg_conn).create(user, "p", "c")
        agent = AgentsRepository(pg_conn).create(user, "a", "draft", description="d", prompt_id=str(prompt["id"]))
        assert _status(_update(app, pg_conn, user, agent["id"], prompt_id="creative")) == 200
        assert _stored(pg_conn, agent["id"]) == (None, "creative")
        assert _status(_update(app, pg_conn, user, agent["id"], prompt_id=str(prompt["id"]))) == 200
        assert _stored(pg_conn, agent["id"]) == (str(prompt["id"]), None)
        assert _status(_update(app, pg_conn, user, agent["id"], prompt_id="strict")) == 200
        assert _status(_update(app, pg_conn, user, agent["id"], prompt_id="default")) == 200
        assert _stored(pg_conn, agent["id"]) == (None, None)

    def test_rejects_garbage(self, app, pg_conn):
        user = "u-update-garbage"
        agent = AgentsRepository(pg_conn).create(user, "a", "draft", description="d", prompt_id="creative")
        assert _status(_update(app, pg_conn, user, agent["id"], prompt_id="not-a-uuid")) == 400
        assert _stored(pg_conn, agent["id"]) == (None, "creative")

    def test_get_agent_returns_the_preset(self, app, pg_conn):
        from docsgpt.api.user.agents.routes import GetAgent

        user = "u-get-preset"
        agent = AgentsRepository(pg_conn).create(user, "a", "draft", description="d", prompt_id="creative")
        with _patch_db(pg_conn), app.test_request_context(f"/api/get_agent?id={agent['id']}"):
            from flask import request

            request.decoded_token = {"sub": user}
            response = GetAgent().get()
        assert response.status_code == 200
        assert response.json["prompt_id"] == "creative"


class TestAdoptTemplate:
    def test_the_adopted_copy_keeps_the_preset(self, app, pg_conn):
        from docsgpt.api.user.agents.routes import AdoptAgent

        template = AgentsRepository(pg_conn).create(
            "__system__", "Tpl", "template", description="d", prompt_id="strict"
        )
        with _patch_db(pg_conn), app.test_request_context(f"/api/adopt_agent?id={template['id']}", method="POST"):
            from flask import request

            request.decoded_token = {"sub": "u-adopt-preset"}
            response = AdoptAgent().post()
        assert _status(response) == 200, response.json
        adopted = AgentsRepository(pg_conn).list_for_user("u-adopt-preset")[0]
        assert adopted["prompt_id"] == "strict"


class TestPortability:
    @pytest.mark.parametrize("preset", ["creative", "strict"])
    def test_export_names_the_preset_and_import_restores_it(self, pg_conn, preset):
        from docsgpt.api.user.agents.portability import (
            agent_to_yaml,
            apply_import,
            parse_agent_yaml,
            plan_import,
            serialize_agent,
        )

        user = f"u-port-{preset}"
        agent = AgentsRepository(pg_conn).create(
            user, "Bot", "published", description="d", chunks=2, retriever="classic", prompt_id=preset
        )
        export = serialize_agent(pg_conn, AgentsRepository(pg_conn).get(str(agent["id"]), user), user)
        assert export["spec"]["prompt"] == preset

        doc = parse_agent_yaml(agent_to_yaml(export))
        doc["metadata"].pop("slug", None)
        doc["metadata"].pop("id", None)
        doc["spec"]["name"] = "Bot copy"
        other = f"{user}-importer"
        assert plan_import(pg_conn, other, doc)["prompt"]["status"] == "preset"
        result = apply_import(pg_conn, other, doc)
        imported = AgentsRepository(pg_conn).get(str(result["agent_id"]), other)
        assert imported["prompt_id"] == preset
        assert PromptsRepository(pg_conn).list_for_user(other) == []

    def test_reimport_switches_a_prompt_row_to_a_preset(self, pg_conn):
        from docsgpt.api.user.agents.portability import API_VERSION, apply_import, ensure_agent_slug

        user = "u-port-switch"
        prompt = PromptsRepository(pg_conn).create(user, "Sys", "Be terse")
        agent = AgentsRepository(pg_conn).create(
            user, "Bot", "published", description="d", chunks=2, retriever="classic", prompt_id=str(prompt["id"])
        )
        slug = ensure_agent_slug(pg_conn, agent, user)
        doc = {
            "apiVersion": API_VERSION,
            "kind": "Agent",
            "metadata": {"slug": slug},
            "spec": {"name": "Bot", "retriever": "classic", "prompt": "creative"},
        }
        apply_import(pg_conn, user, doc)
        assert _stored(pg_conn, agent["id"]) == (None, "creative")

    def test_an_unknown_prompt_name_imports_as_default(self, pg_conn):
        from docsgpt.api.user.agents.portability import API_VERSION, apply_import

        doc = {
            "apiVersion": API_VERSION,
            "kind": "Agent",
            "metadata": {"slug": "odd"},
            "spec": {"name": "Odd", "retriever": "classic", "prompt": "bogus"},
        }
        result = apply_import(pg_conn, "u-port-odd", doc)
        assert _stored(pg_conn, result["agent_id"]) == (None, None)


class TestRuntime:
    def test_api_key_run_renders_the_preset(self, pg_conn):
        from docsgpt.api.answer.services.stream_processor import StreamProcessor

        AgentsRepository(pg_conn).create("u-run", "a", "published", key="preset-run-key", prompt_id="creative")

        @contextmanager
        def _yield():
            yield pg_conn

        sp = StreamProcessor({}, {"sub": "u-run"})
        with patch("docsgpt.api.answer.services.stream_processor.db_readonly", _yield):
            data = sp._get_data_from_api_key("preset-run-key")
        assert data["prompt_id"] == "creative"

    def test_agent_id_lookup_sees_the_preset(self, pg_conn):
        from docsgpt.api.answer.services.stream_processor import StreamProcessor

        agent = AgentsRepository(pg_conn).create("u-run2", "a", "published", key="preset-run-key2", prompt_id="strict")

        @contextmanager
        def _yield():
            yield pg_conn

        sp = StreamProcessor({}, {"sub": "u-run2"})
        with patch("docsgpt.api.answer.services.stream_processor.db_readonly", _yield), patch(
            "docsgpt.api.answer.services.stream_processor.db_session", _yield
        ):
            key, _, _ = sp._get_agent_key(str(agent["id"]), "u-run2")
        assert key == "preset-run-key2"

    def test_scheduled_run_loads_the_preset(self, pg_conn):
        from docsgpt.api.user import scheduler_worker

        agent = AgentsRepository(pg_conn).create("u-sched", "a", "published", prompt_id="creative")

        class _Engine:
            @contextmanager
            def connect(self):
                yield pg_conn

        with patch.object(scheduler_worker, "get_engine", lambda: _Engine()):
            config = scheduler_worker._agent_config_for_schedule({"agent_id": str(agent["id"])})
        assert config["prompt_id"] == "creative"

    def test_continuation_loads_the_preset(self, pg_conn):
        from docsgpt.background.continuation import _agent_config

        agent = AgentsRepository(pg_conn).create("u-cont", "a", "published", prompt_id="strict")
        config = _agent_config(pg_conn, {"agent_id": str(agent["id"]), "user_id": "u-cont"}, None)
        assert config["prompt_id"] == "strict"

    def test_headless_run_composes_the_creative_prompt(self, pg_conn):
        from docsgpt.agents import headless_runner
        from docsgpt.prompts.composer import compose_preset

        agent = AgentsRepository(pg_conn).create("u-headless", "a", "published", prompt_id="creative", chunks=0)
        config = AgentsRepository(pg_conn).get(str(agent["id"]), "u-headless")
        captured = {}

        def _resolve(content, prompt_id, agent_type):
            captured["prompt_id"] = prompt_id
            captured["content"] = content
            raise RuntimeError("stop")

        with patch.object(headless_runner, "resolve_prompt_skeleton", _resolve), patch.object(
            headless_runner.QuotaService, "check", return_value=None
        ), pytest.raises(RuntimeError):
            headless_runner._run_agent_headless(config, "hi")
        assert captured["prompt_id"] == "creative"
        assert captured["content"] == compose_preset("creative")


class TestShareConversation:
    def _share(self, app, conn, user, conv_id, prompt_id):
        from docsgpt.api.user.sharing.routes import ShareConversation

        @contextmanager
        def _yield():
            yield conn

        with patch("docsgpt.api.user.sharing.routes.db_session", _yield), patch(
            "docsgpt.api.user.sharing.routes.db_readonly", _yield
        ), app.test_request_context(
            "/api/share?isPromptable=true",
            method="POST",
            json={"conversation_id": conv_id, "chunks": 2, "prompt_id": prompt_id},
        ):
            from flask import request

            request.decoded_token = {"sub": user}
            return ShareConversation().post()

    def test_the_share_agent_keeps_the_preset_and_is_not_reused_for_the_default(self, app, pg_conn):
        from docsgpt.storage.db.repositories.conversations import ConversationsRepository
        from docsgpt.storage.db.repositories.shared_conversations import SharedConversationsRepository

        user = "u-share-preset"
        conv_id = str(ConversationsRepository(pg_conn).create(user, name="c")["id"])

        creative = self._share(app, pg_conn, user, conv_id, "creative")
        assert creative.status_code == 201
        share = SharedConversationsRepository(pg_conn).find_by_uuid(creative.json["identifier"])
        assert AgentsRepository(pg_conn).find_by_key(share["api_key"])["prompt_id"] == "creative"

        again = self._share(app, pg_conn, user, conv_id, "creative")
        assert again.status_code == 200

        default = self._share(app, pg_conn, user, conv_id, "default")
        assert default.status_code == 201
        share = SharedConversationsRepository(pg_conn).find_by_uuid(default.json["identifier"])
        assert AgentsRepository(pg_conn).find_by_key(share["api_key"])["prompt_id"] is None
