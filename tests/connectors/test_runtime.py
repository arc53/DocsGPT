"""Runtime use of connections: tool execution, sharing modes and scheduled sync."""

from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import text

from docsgpt.security.encryption import encrypt_json


@contextmanager
def _service_db(conn):
    @contextmanager
    def _yield():
        yield conn

    with patch.multiple("docsgpt.connectors.service", db_session=_yield, db_readonly=_yield), \
            patch.multiple("docsgpt.connectors.resolve", db_readonly=_yield):
        yield


def _connection(conn, user="alice", provider="telegram", status="connected", secrets=None,
                auth_kind="api_key", server_url=None) -> str:
    return str(conn.execute(
        text(
            "INSERT INTO connector_sessions (user_id, provider, connector_key, auth_kind, status, "
            "account_label, server_url, encrypted_credentials) VALUES (:u, :p, :p, :a, :s, :l, :url, :e) RETURNING id"
        ),
        {"u": user, "p": provider, "a": auth_kind, "s": status, "l": f"{user}-label", "url": server_url,
         "e": encrypt_json(secrets or {"credentials": {"token": f"{user}-token"}}, user)},
    ).scalar())


def _tool(connection_id, *, user="alice", name="telegram", mode="owner", tool_id="tool-1"):
    return {
        "id": tool_id,
        "user_id": user,
        "name": name,
        "config": {},
        "actions": [{"name": "telegram_send_message", "active": True, "require_approval": False}],
        "connection_id": connection_id,
        "credential_mode": mode,
    }


def _call(action="telegram_send_message"):
    return SimpleNamespace(id="call-1", name=action, arguments="{}", thought_signature=None)


def _executor(user="alice", headless=False):
    from docsgpt.agents.tool_executor import ToolExecutor

    executor = ToolExecutor(user=user, headless=headless)
    return executor


def _pause(executor, tool):
    with patch("docsgpt.agents.tool_executor.ToolActionParser") as parser:
        parser.return_value.parse_args.return_value = ("t1", "telegram_send_message", {})
        return executor.check_pause({"t1": tool}, _call(), "OpenAILLM")


class TestResolution:
    def test_owner_mode_uses_owner_connection(self, pg_conn):
        from docsgpt.connectors.resolve import resolve_connection

        cid = _connection(pg_conn)
        with _service_db(pg_conn):
            resolved = resolve_connection(_tool(cid), "bob")
        assert resolved.available and resolved.connection_id == cid
        assert resolved.delegated is True
        assert resolved.connector_name == "Telegram"

    def test_member_mode_uses_invokers_connection(self, pg_conn):
        from docsgpt.connectors.resolve import resolve_connection

        owner = _connection(pg_conn)
        bobs = _connection(pg_conn, user="bob")
        with _service_db(pg_conn):
            resolved = resolve_connection(_tool(owner, mode="member"), "bob")
        assert resolved.connection_id == bobs
        assert resolved.delegated is False

    def test_member_with_several_accounts_uses_the_one_last_used(self, pg_conn):
        from docsgpt.connectors.resolve import resolve_connection

        owner = _connection(pg_conn)
        older = _connection(pg_conn, user="bob")
        pg_conn.execute(text(
            "UPDATE connector_sessions SET account_label = 'bob-home', last_used_at = now() - interval '1 day' "
            "WHERE id = CAST(:i AS uuid)"
        ), {"i": older})
        newer = _connection(pg_conn, user="bob")
        pg_conn.execute(text(
            "UPDATE connector_sessions SET last_used_at = now() WHERE id = CAST(:i AS uuid)"
        ), {"i": newer})
        with _service_db(pg_conn):
            resolved = resolve_connection(_tool(owner, mode="member"), "bob")
        assert resolved.available and resolved.connection_id == newer

    def test_member_gets_the_account_they_just_connected(self, pg_conn):
        from docsgpt.connectors.resolve import resolve_connection

        owner = _connection(pg_conn)
        used = _connection(pg_conn, user="bob")
        pg_conn.execute(text(
            "UPDATE connector_sessions SET account_label = 'bob-work', created_at = now() - interval '30 days', "
            "updated_at = now() - interval '30 days', last_used_at = now() - interval '1 hour' "
            "WHERE id = CAST(:i AS uuid)"
        ), {"i": used})
        # Added by "Connect to continue": never used yet.
        added = _connection(pg_conn, user="bob")
        with _service_db(pg_conn):
            resolved = resolve_connection(_tool(owner, mode="member"), "bob")
        assert resolved.available and resolved.connection_id == added

    def test_member_mode_without_own_connection_is_unavailable(self, pg_conn):
        from docsgpt.connectors.resolve import resolve_connection

        owner = _connection(pg_conn)
        with _service_db(pg_conn):
            resolved = resolve_connection(_tool(owner, mode="member"), "bob")
        assert resolved.available is False
        assert resolved.connector_name == "Telegram"

    def test_member_mode_matches_mcp_server(self, pg_conn):
        from docsgpt.connectors.resolve import resolve_connection

        owner = _connection(pg_conn, provider="mcp:https://a.example.com", auth_kind="mcp_oauth",
                            server_url="https://a.example.com", secrets={"tokens": {"access_token": "x"}})
        _connection(pg_conn, user="bob", provider="mcp:https://b.example.com", auth_kind="mcp_oauth",
                    server_url="https://b.example.com", secrets={"tokens": {"access_token": "y"}})
        with _service_db(pg_conn):
            resolved = resolve_connection(_tool(owner, name="mcp_tool", mode="member"), "bob")
        assert resolved.available is False

    def test_resource_cannot_borrow_another_users_connection(self, pg_conn):
        from docsgpt.connectors.resolve import resolve_connection

        mallorys_target = _connection(pg_conn, user="victim")
        with _service_db(pg_conn):
            resolved = resolve_connection(_tool(mallorys_target, user="mallory"), "mallory")
        assert resolved.available is False and resolved.row is None


class TestExecutor:
    def test_credentials_come_from_the_connection(self, pg_conn):
        cid = _connection(pg_conn)
        executor = _executor()
        tool = _tool(cid)
        with _service_db(pg_conn), patch("docsgpt.agents.tool_executor.ToolManager") as manager:
            executor._get_or_load_tool(tool, "t1", "telegram_send_message")
        config = manager.return_value.load_tool.call_args.kwargs["tool_config"]
        assert config["token"] == "alice-token"
        assert "encrypted_credentials" not in config

    def test_owner_mode_delegation_is_audited(self, pg_conn, caplog):
        cid = _connection(pg_conn)
        executor = _executor(user="bob")
        with _service_db(pg_conn), patch("docsgpt.agents.tool_executor.ToolManager"), \
                caplog.at_level(logging.INFO, logger="docsgpt.connectors.resolve"):
            executor._get_or_load_tool(_tool(cid), "t1", "telegram_send_message")
        record = next(r for r in caplog.records if r.message == "tool_credential_delegation")
        assert record.connection_id == cid and record.invoker == "bob"

    def test_needs_reconnect_pauses_on_connect_card(self, pg_conn):
        cid = _connection(pg_conn, status="reconnect_needed")
        with _service_db(pg_conn):
            pause = _pause(_executor(), _tool(cid))
        assert pause["pause_type"] == "awaiting_approval"
        # The caller's own connection: the card can reconnect it in place.
        assert pause["connection_required"] == {
            "connector_key": "telegram", "connector_name": "Telegram", "status": "reconnect_needed",
            "connection_id": cid, "owner_account": False,
        }

    def test_owners_broken_account_is_not_handed_to_the_member(self, pg_conn):
        cid = _connection(pg_conn, status="reconnect_needed")
        with _service_db(pg_conn):
            pause = _pause(_executor(user="bob"), _tool(cid))
        required = pause["connection_required"]
        assert required["owner_account"] is True
        assert "connection_id" not in required

    def test_member_without_connection_pauses(self, pg_conn):
        cid = _connection(pg_conn)
        with _service_db(pg_conn):
            pause = _pause(_executor(user="bob"), _tool(cid, mode="member"))
        assert pause["connection_required"]["status"] == "missing"

    def test_headless_run_is_denied_not_paused(self, pg_conn):
        cid = _connection(pg_conn, status="disconnected")
        with _service_db(pg_conn):
            pause = _pause(_executor(headless=True), _tool(cid))
        assert pause["pause_type"] == "headless_denied"
        assert pause["error_type"] == "connection_required"

    def test_connected_tool_does_not_pause(self, pg_conn):
        cid = _connection(pg_conn)
        with _service_db(pg_conn):
            assert _pause(_executor(), _tool(cid)) is None

    def test_mcp_tool_gets_connection_id_not_tokens(self, pg_conn):
        cid = _connection(pg_conn, provider="mcp:https://m.example.com", auth_kind="mcp_oauth",
                          server_url="https://m.example.com", secrets={"tokens": {"access_token": "secret"}})
        tool = {**_tool(cid, name="mcp_tool"), "config": {"server_url": "https://m.example.com/mcp",
                                                         "auth_type": "oauth"}}
        with _service_db(pg_conn), patch("docsgpt.agents.tool_executor.ToolManager") as manager:
            _executor()._get_or_load_tool(tool, "t1", "search")
        config = manager.return_value.load_tool.call_args.kwargs["tool_config"]
        assert config["connection_id"] == cid
        assert "secret" not in str(config)

    def test_stored_connection_id_in_config_is_ignored(self, pg_conn):
        """Only a resolved connection reaches the tool; a config value never does."""
        victim = _connection(pg_conn, user="victim", provider="mcp:https://m.example.com", auth_kind="mcp_oauth",
                             server_url="https://m.example.com", secrets={"tokens": {"access_token": "v"}})
        tool = {**_tool(None, name="mcp_tool"), "config": {"server_url": "https://m.example.com/mcp",
                                                          "auth_type": "oauth", "connection_id": victim}}
        with _service_db(pg_conn), patch("docsgpt.agents.tool_executor.ToolManager") as manager:
            _executor()._get_or_load_tool(tool, "t1", "search")
        config = manager.return_value.load_tool.call_args.kwargs["tool_config"]
        assert "connection_id" not in config


def _telegram_tool(connection_id, *, user="alice", mode="owner"):
    from docsgpt.agents.tools.telegram import TelegramTool
    from docsgpt.connectors.service import _transform_actions

    return {
        **_tool(connection_id, user=user, mode=mode),
        "actions": _transform_actions(TelegramTool({}).get_actions_metadata()),
    }


def _run_send(executor, tool, arguments):
    with patch("docsgpt.agents.tool_executor.ToolActionParser") as parser, \
            patch("docsgpt.agents.tool_executor.ToolManager") as manager:
        parser.return_value.parse_args.return_value = ("t1", "telegram_send_message", arguments)
        gen = executor.execute({"t1": tool}, _call(), "OpenAILLM")
        while True:
            try:
                next(gen)
            except StopIteration:
                break
    return manager.return_value.load_tool.return_value.execute_action.call_args


class TestTelegramDefaultChat:
    def test_the_connection_offers_a_default_chat_field(self):
        from docsgpt.connectors import catalog

        fields = {f.key: f for f in catalog.get_definition("telegram").credential_fields}
        chat = fields["chat_id"]
        assert chat.secret is False and chat.required is False
        assert chat.parameter == "chat_id"
        assert chat.hint
        assert chat.to_dict()["hint"] == chat.hint

    def test_the_model_is_not_asked_for_a_chat_the_connection_sets(self, pg_conn):
        cid = _connection(pg_conn, secrets={"credentials": {"token": "t", "chat_id": "-1001"}})
        with _service_db(pg_conn):
            functions = _executor().prepare_tools_for_llm({"t1": _telegram_tool(cid)})
        by_name = {f["function"]["name"]: f["function"]["parameters"] for f in functions}
        assert "chat_id" not in by_name["telegram_send_message"]["properties"]
        assert "chat_id" not in by_name["telegram_send_image"]["properties"]

    def test_without_a_default_chat_the_model_still_names_one(self, pg_conn):
        cid = _connection(pg_conn, secrets={"credentials": {"token": "t"}})
        with _service_db(pg_conn):
            functions = _executor().prepare_tools_for_llm({"t1": _telegram_tool(cid)})
        params = {f["function"]["name"]: f["function"]["parameters"] for f in functions}
        assert "chat_id" in params["telegram_send_message"]["properties"]

    def test_the_default_chat_wins_over_what_the_model_sends(self, pg_conn):
        cid = _connection(pg_conn, secrets={"credentials": {"token": "t", "chat_id": "-1001"}})
        with _service_db(pg_conn):
            call = _run_send(_executor(), _telegram_tool(cid), {"text": "hi", "chat_id": "666"})
        assert call.kwargs == {"text": "hi", "chat_id": "-1001"}

    def test_each_member_uses_their_own_chat(self, pg_conn):
        owner = _connection(pg_conn, secrets={"credentials": {"token": "t", "chat_id": "-1001"}})
        _connection(pg_conn, user="bob", secrets={"credentials": {"token": "b", "chat_id": "-2002"}})
        with _service_db(pg_conn):
            call = _run_send(_executor(user="bob"), _telegram_tool(owner, mode="member"), {"text": "hi"})
        assert call.kwargs == {"text": "hi", "chat_id": "-2002"}


class TestAccountsTellApartForTheModel:
    @staticmethod
    def _two_bots(pg_conn, names):
        tools = {}
        for index, name in enumerate(names):
            cid = _connection(pg_conn)
            pg_conn.execute(text(
                "UPDATE connector_sessions SET account_label = :l, account_name = :n WHERE id = CAST(:i AS uuid)"
            ), {"l": f"…{index}abc", "n": name, "i": cid})
            tools[f"t{index}"] = {**_telegram_tool(cid), "id": f"tool-{index}"}
        return tools

    def test_named_accounts_name_the_functions(self, pg_conn):
        tools = self._two_bots(pg_conn, ["Alerts bot", "Ops: on-call!"])
        with _service_db(pg_conn):
            executor = _executor()
            functions = {f["function"]["name"]: f["function"] for f in executor.prepare_tools_for_llm(tools)}
        assert {"telegram_send_message_alerts_bot", "telegram_send_message_ops_on_call"} <= set(functions)
        assert "Alerts bot" in functions["telegram_send_message_alerts_bot"]["description"]
        assert executor._name_to_tool["telegram_send_message_ops_on_call"] == ("t1", "telegram_send_message")

    def test_unnamed_accounts_use_their_labels(self, pg_conn):
        tools = self._two_bots(pg_conn, [None, None])
        with _service_db(pg_conn):
            names = {f["function"]["name"] for f in _executor().prepare_tools_for_llm(tools)}
        assert {"telegram_send_message_0abc", "telegram_send_message_1abc"} <= names

    def test_different_services_are_named_after_the_service(self, pg_conn):
        tools = {}
        for index, (host, name) in enumerate((("a.example.com", "Wiki"), ("b.example.com", "Tracker"))):
            cid = _connection(pg_conn, provider=f"mcp:https://{host}", auth_kind="mcp_oauth",
                              server_url=f"https://{host}", secrets={"tokens": {"access_token": "x"}})
            pg_conn.execute(text("UPDATE connector_sessions SET connector_key = 'custom_mcp', display_name = :n "
                                 "WHERE id = CAST(:i AS uuid)"), {"n": name, "i": cid})
            tools[f"t{index}"] = {**_tool(cid, name="mcp_tool", tool_id=f"tool-{index}"),
                                  "actions": [{"name": "search", "description": "Search", "active": True}]}
        with _service_db(pg_conn):
            functions = {f["function"]["name"]: f["function"] for f in _executor().prepare_tools_for_llm(tools)}
        assert set(functions) == {"search_wiki", "search_tracker"}
        assert functions["search_wiki"]["description"] == "Search (Wiki)"

    def test_names_stay_within_provider_limits(self, pg_conn):
        tools = self._two_bots(pg_conn, ["x" * 80, "x" * 80])
        with _service_db(pg_conn):
            names = [f["function"]["name"] for f in _executor().prepare_tools_for_llm(tools)]
        assert len(names) == len(set(names))
        assert all(len(n) <= 64 and n.replace("_", "").replace("-", "").isalnum() for n in names)


class TestScheduledSync:
    def test_connector_sources_with_a_connection_are_dispatched(self, pg_conn):
        from docsgpt import worker

        cid = _connection(pg_conn, provider="google_drive", auth_kind="oauth",
                          secrets={"token_info": {"access_token": "a"}})
        pg_conn.execute(text(
            "INSERT INTO sources (user_id, name, type, sync_frequency, connection_id, remote_data) "
            "VALUES ('alice', 'Drive', 'connector:file', 'weekly', CAST(:c AS uuid), '{\"provider\": \"google_drive\"}')"
        ), {"c": cid})
        pg_conn.execute(text(
            "INSERT INTO sources (user_id, name, type, sync_frequency) VALUES ('alice', 'Old', 'connector:file', 'weekly')"
        ))

        @contextmanager
        def _yield():
            yield pg_conn

        with patch.object(worker, "db_readonly", _yield), patch(
            "docsgpt.api.user.tasks.sync_connector_source.delay"
        ) as delay:
            counts = worker.sync_worker(MagicMock(), "weekly")
        assert delay.call_count == 1
        assert counts["sync_dispatched"] == 1
        assert counts["sync_skipped"] == 1

    def test_paused_repository_is_skipped_until_reconnected(self, pg_conn):
        """A GitHub or S3 source paused for reconnect is not retried (and failed) on every schedule."""
        from docsgpt import worker

        cid = _connection(pg_conn, provider="github", status="reconnect_needed",
                          secrets={"credentials": {"access_token": "revoked"}})
        pg_conn.execute(text(
            "INSERT INTO sources (user_id, name, type, sync_frequency, connection_id, remote_data, metadata) "
            "VALUES ('alice', 'acme/api', 'github', 'daily', CAST(:c AS uuid), '{\"repo_url\": \"acme/api\"}', "
            "'{\"sync_state\": \"paused_reconnect\"}')"
        ), {"c": cid})

        @contextmanager
        def _yield():
            yield pg_conn

        with patch.object(worker, "db_readonly", _yield), patch.object(worker, "sync") as sync:
            counts = worker.sync_worker(MagicMock(), "daily")
        sync.assert_not_called()
        assert counts["sync_skipped"] == 1

    def test_paused_connection_is_not_synced(self, pg_conn):
        from docsgpt import worker

        cid = _connection(pg_conn, provider="google_drive", auth_kind="oauth", status="reconnect_needed",
                          secrets={"token_info": {}})
        source = pg_conn.execute(text(
            "INSERT INTO sources (user_id, name, type, sync_frequency, connection_id) "
            "VALUES ('alice', 'Drive', 'connector:file', 'weekly', CAST(:c AS uuid)) RETURNING id"
        ), {"c": cid}).scalar()

        @contextmanager
        def _yield():
            yield pg_conn

        with patch.object(worker, "db_readonly", _yield), patch.object(worker, "ingest_connector") as ingest:
            result = worker.sync_connector_source(MagicMock(), str(source))
        assert result == {"status": "paused"}
        ingest.assert_not_called()

    def test_disabled_connector_is_not_synced(self, pg_conn):
        from docsgpt import worker
        from docsgpt.storage.db.repositories.connector_policies import ConnectorPoliciesRepository

        cid = _connection(pg_conn, provider="google_drive", auth_kind="oauth",
                          secrets={"token_info": {"access_token": "a"}})
        source = pg_conn.execute(text(
            "INSERT INTO sources (user_id, name, type, sync_frequency, connection_id, remote_data) "
            "VALUES ('alice', 'Drive', 'connector:file', 'weekly', CAST(:c AS uuid), "
            "'{\"provider\": \"google_drive\"}') RETURNING id"
        ), {"c": cid}).scalar()
        ConnectorPoliciesRepository(pg_conn).upsert("google_drive", enabled=False)

        @contextmanager
        def _yield():
            yield pg_conn

        with patch.object(worker, "db_readonly", _yield), patch.object(worker, "ingest_connector") as ingest:
            result = worker.sync_connector_source(MagicMock(), str(source))
        assert result == {"status": "disabled"}
        ingest.assert_not_called()

    def test_disabled_connector_gives_remote_sync_no_credentials(self, pg_conn):
        from docsgpt import worker
        from docsgpt.storage.db.repositories.connector_policies import ConnectorPoliciesRepository

        cid = _connection(pg_conn, provider="s3", auth_kind="api_key",
                          secrets={"credentials": {"aws_access_key_id": "AKIA", "aws_secret_access_key": "s"}})

        @contextmanager
        def _yield():
            yield pg_conn

        with patch.object(worker, "db_readonly", _yield):
            assert worker._with_connection_credentials({"bucket": "b"}, cid)["aws_access_key_id"] == "AKIA"
            ConnectorPoliciesRepository(pg_conn).upsert("s3", enabled=False)
            assert worker._with_connection_credentials({"bucket": "b"}, cid) is None

    def test_repository_url_gets_the_connections_token(self, pg_conn):
        """A GitHub source's loader input is a plain URL, not JSON."""
        from docsgpt import worker

        cid = _connection(pg_conn, provider="github", auth_kind="api_key",
                          secrets={"credentials": {"access_token": "github_pat_x"}})

        @contextmanager
        def _yield():
            yield pg_conn

        with patch.object(worker, "db_readonly", _yield):
            data = worker._with_connection_credentials("https://github.com/acme/private", cid)
            as_json = worker._with_connection_credentials('{"search_queries": ["x"]}', cid)
        assert data == {"url": "https://github.com/acme/private", "access_token": "github_pat_x"}
        assert json.loads(as_json)["access_token"] == "github_pat_x"

    def test_oauth_connection_gives_its_current_access_token(self, pg_conn):
        """A GitHub App sign-in keeps an OAuth token, refreshed before use."""
        from docsgpt import worker

        cid = _connection(pg_conn, provider="github", auth_kind="oauth",
                          secrets={"token_info": {"access_token": "ghu_fresh", "refresh_token": "ghr_x"}})

        @contextmanager
        def _yield():
            yield pg_conn

        with patch.object(worker, "db_readonly", _yield), _service_db(pg_conn), patch(
            "docsgpt.connectors.service.get_valid_token_info", return_value={"access_token": "ghu_fresh"},
        ) as valid:
            data = worker._with_connection_credentials({"repo_url": "acme/private"}, cid)
        valid.assert_called_once_with(cid)
        assert data == {"repo_url": "acme/private", "access_token": "ghu_fresh"}

    def test_rejected_token_flags_the_connection(self, pg_conn):
        """A revoked token pauses the source for reconnect instead of failing every sync."""
        from docsgpt import worker
        from docsgpt.connectors.service import ConnectionUnavailable
        from docsgpt.parser.remote.github_loader import GitHubTokenRejected

        loader = MagicMock()
        loader.load_data.side_effect = GitHubTokenRejected("revoked")
        task = MagicMock()
        task.request.retries = 1
        with patch.object(worker.RemoteCreator, "create_loader", return_value=loader), patch.object(
            worker, "_with_connection_credentials", return_value={"url": "acme/r", "access_token": "t"},
        ), patch.object(worker, "publish_user_event"), patch(
            "docsgpt.connectors.service.mark_reconnect_needed",
        ) as flag:
            with pytest.raises(ConnectionUnavailable):
                worker.remote_worker(task, "acme/r", "repo", "alice", "github", connection_id="c-1")
        flag.assert_called_once()
        assert flag.call_args.args[0] == "c-1"

    def test_sync_runs_as_the_connection_without_a_browser(self, pg_conn):
        from docsgpt import worker

        cid = _connection(pg_conn, provider="google_drive", auth_kind="oauth",
                          secrets={"token_info": {"access_token": "a"}})
        source = pg_conn.execute(text(
            "INSERT INTO sources (user_id, name, type, sync_frequency, connection_id, remote_data) "
            "VALUES ('alice', 'Drive', 'connector:file', 'daily', CAST(:c AS uuid), "
            "'{\"provider\": \"google_drive\", \"folder_ids\": [\"f\"], \"recursive\": false}') RETURNING id"
        ), {"c": cid}).scalar()

        @contextmanager
        def _yield():
            yield pg_conn

        with patch.object(worker, "db_readonly", _yield), patch.object(
            worker, "ingest_connector", return_value={"tokens": 1}
        ) as ingest:
            result = worker.sync_connector_source(MagicMock(), str(source))
        assert result["status"] == "success"
        kwargs = ingest.call_args.kwargs
        assert kwargs["connection_id"] == cid
        assert kwargs["operation_mode"] == "sync"
        assert kwargs["folder_ids"] == ["f"] and kwargs["recursive"] is False
        assert "session_token" not in kwargs


@pytest.mark.parametrize("secret_key", ["token_info", "tokens", "client_info", "encrypted_credentials",
                                        "client_secret", "refresh_token", "access_token"])
def test_redaction_covers_connection_secrets(secret_key):
    from docsgpt.storage.db.redaction import REDACTED, redact_secrets

    assert redact_secrets({secret_key: {"x": "y"}})[secret_key] == REDACTED


class TestMcpServerMismatch:
    def test_connection_for_another_server_is_not_applied(self, pg_conn):
        """A key stored for one MCP server is never sent to a tool now pointing at another."""
        from docsgpt.connectors import service

        cid = _connection(pg_conn, provider="custom_mcp", server_url="https://old.example.com",
                          secrets={"credentials": {"bearer_token": "old-server-secret"}})
        tool = {**_tool(cid, name="mcp_tool"), "config": {"server_url": "https://new.example.com/mcp",
                                                         "auth_type": "bearer"}}
        with _service_db(pg_conn), patch("docsgpt.agents.tool_executor.ToolManager") as manager:
            with pytest.raises(service.ConnectionUnavailable):
                _executor()._get_or_load_tool(tool, "t1", "search")
        manager.return_value.load_tool.assert_not_called()

    @pytest.mark.parametrize("tool_name, provider, server_url", [
        # A service's key without a server of its own is not an MCP server's.
        ("mcp_tool", "telegram", None),
        ("mcp_tool", "ntfy", None),
        # A custom server connection that names no server has nowhere to go.
        ("mcp_tool", "custom_mcp", None),
        # A tool only runs on a connection of the connector that provides it.
        ("ntfy", "telegram", None),
        ("telegram", "ntfy", None),
        ("telegram", "custom_mcp", "https://new.example.com"),
    ])
    def test_connection_of_another_connector_is_not_applied(self, pg_conn, tool_name, provider, server_url):
        from docsgpt.connectors import service

        cid = _connection(pg_conn, provider=provider, server_url=server_url,
                          secrets={"credentials": {"token": "bot-token", "bearer_token": "bot-token"}})
        tool = {**_tool(cid, name=tool_name), "config": {"server_url": "https://new.example.com/mcp",
                                                        "auth_type": "bearer"}}
        with _service_db(pg_conn), patch("docsgpt.agents.tool_executor.ToolManager") as manager:
            with pytest.raises(service.ConnectionUnavailable):
                _executor()._get_or_load_tool(tool, "t1", "search")
        manager.return_value.load_tool.assert_not_called()

    def test_legacy_mcp_connection_is_still_applied_to_its_server(self, pg_conn):
        """Rows from before connector keys are named from their ``mcp:`` provider."""
        cid = _connection(pg_conn, provider="mcp:https://m.example.com", auth_kind="mcp_oauth",
                          server_url=None, secrets={"tokens": {"access_token": "x"}})
        pg_conn.execute(text("UPDATE connector_sessions SET connector_key = NULL WHERE id = CAST(:i AS uuid)"),
                        {"i": cid})
        tool = {**_tool(cid, name="mcp_tool"), "config": {"server_url": "https://m.example.com/mcp",
                                                         "auth_type": "oauth"}}
        with _service_db(pg_conn), patch("docsgpt.agents.tool_executor.ToolManager") as manager:
            _executor()._get_or_load_tool(tool, "t1", "search")
        assert manager.return_value.load_tool.call_args.kwargs["tool_config"]["connection_id"] == cid

    def test_save_keeps_previous_connection_only_for_the_same_server(self, pg_conn):
        from docsgpt.api.user.tools.mcp import _previous_connection

        @contextmanager
        def _yield():
            yield pg_conn

        cid = _connection(pg_conn, provider="custom_mcp", server_url="https://old.example.com")
        existing = {"connection_id": cid}
        same = {"server_url": "https://old.example.com/mcp", "auth_type": "bearer"}
        with patch("docsgpt.api.user.tools.mcp.db_readonly", _yield):
            assert _previous_connection(existing, same, "alice") == cid
            assert _previous_connection(existing, {**same, "server_url": "https://new.example.com/mcp"}, "alice") is None
            assert _previous_connection(None, same, "alice") is None
            # Someone else's connection, or one that signs in another way, is not kept.
            assert _previous_connection(existing, same, "bob") is None
            assert _previous_connection(existing, {**same, "auth_type": "oauth"}, "alice") is None


class TestExternalApiCallers:
    """An agent called with its API key runs as the owner, and nobody can approve there."""

    def _external(self, allowlist=None):
        from docsgpt.agents.tool_executor import ToolExecutor

        return ToolExecutor(user="alice", external_caller=True, api_write_allowlist=allowlist)

    def test_owner_account_write_is_denied(self, pg_conn):
        cid = _connection(pg_conn)
        with _service_db(pg_conn):
            pause = _pause(self._external(), _tool(cid))
        assert pause["pause_type"] == "headless_denied"
        assert pause["error_type"] == "tool_not_allowed"
        assert "Access details" in pause["deny_reason"]

    def test_even_always_allow_writes_are_denied(self, pg_conn):
        cid = _connection(pg_conn)
        tool = _tool(cid)
        tool["actions"][0]["require_approval"] = False
        with _service_db(pg_conn):
            assert _pause(self._external(), tool)["pause_type"] == "headless_denied"

    def test_allowlisted_write_runs(self, pg_conn):
        cid = _connection(pg_conn)
        with _service_db(pg_conn):
            pause = _pause(self._external(["tool-1:telegram_send_message"]), _tool(cid))
        assert pause is None

    def test_allowlist_does_not_cover_other_actions(self, pg_conn):
        cid = _connection(pg_conn)
        with _service_db(pg_conn):
            pause = _pause(self._external(["tool-1:telegram_send_image"]), _tool(cid))
        assert pause["pause_type"] == "headless_denied"

    def test_missing_connection_is_denied_not_paused(self, pg_conn):
        """The widget cannot show a Connect card."""
        cid = _connection(pg_conn, status="reconnect_needed")
        with _service_db(pg_conn):
            pause = _pause(self._external(), _tool(cid))
        assert pause["pause_type"] == "headless_denied"
        assert pause["error_type"] == "connection_required"

    def test_the_owner_in_the_app_is_not_external(self, pg_conn):
        cid = _connection(pg_conn)
        with _service_db(pg_conn):
            assert _pause(_executor(), _tool(cid)) is None


class TestExternalCallerDetection:
    def test_api_key_request_from_someone_else_is_external(self):
        from docsgpt.api.answer.services.stream_processor import is_external_api_caller

        assert is_external_api_caller({"api_key": "k"}, {"sub": "visitor"}, "alice") is True
        assert is_external_api_caller({"api_key": "k"}, None, "alice") is True

    def test_owner_previewing_their_agent_is_not_external(self):
        from docsgpt.api.answer.services.stream_processor import is_external_api_caller

        assert is_external_api_caller({"api_key": "k"}, {"sub": "alice"}, "alice") is False
        assert is_external_api_caller({}, {"sub": "visitor"}, "alice") is False


class TestApiWriteAllowlistConfig:
    def test_accepts_tool_action_pairs(self):
        from docsgpt.guardrails.config import AgentConfig

        config = AgentConfig.model_validate({"api_write_allowlist": ["tool-1:telegram_send_message"]})
        assert config.api_write_allowlist == ["tool-1:telegram_send_message"]

    def test_rejects_malformed_entries(self):
        from docsgpt.guardrails.config import AgentConfig

        with pytest.raises(Exception):
            AgentConfig.model_validate({"api_write_allowlist": ["no-action-part"]})

    def test_old_configs_still_parse(self):
        from docsgpt.guardrails.config import AgentConfig

        assert AgentConfig.parse({"guardrails": {}}).api_write_allowlist == []


class TestAllowlistOwnership:
    def test_team_editor_cannot_change_the_allowlist(self):
        from docsgpt.api.user.agents.routes import keep_owner_only_config

        existing = {"config": {"api_write_allowlist": ["t:a"]}}
        sent = {"guardrails": {"controls": []}, "api_write_allowlist": ["t:a", "t:b"]}
        assert keep_owner_only_config(sent, existing, True)["api_write_allowlist"] == ["t:a"]
        assert keep_owner_only_config(sent, existing, False)["api_write_allowlist"] == ["t:a", "t:b"]
        assert keep_owner_only_config({}, {"config": None}, True) == {"api_write_allowlist": []}
