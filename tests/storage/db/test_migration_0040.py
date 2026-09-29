"""Migration tests for 0040_connections: columns, backfill and round trip."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import text


pytestmark = pytest.mark.integration

_0037 = "0039_resource_sponsors"  # the revision before 0040_connections


def _alembic_ini() -> Path:
    return Path(__file__).resolve().parents[3] / "docsgpt" / "alembic.ini"


def _run_alembic(url: str, *args: str) -> None:
    subprocess.check_call(
        [sys.executable, "-m", "alembic", "-c", str(_alembic_ini()), *args],
        timeout=120,
        env={**os.environ, "POSTGRES_URI": url},
    )


def _columns(conn, table: str) -> set[str]:
    rows = conn.execute(
        text("SELECT column_name FROM information_schema.columns WHERE table_name = :t"),
        {"t": table},
    ).fetchall()
    return {r[0] for r in rows}


def _seed_legacy(conn) -> dict:
    """Rows as a pre-0040 install left them."""
    ids = {}
    ids["drive"] = conn.execute(
        text(
            "INSERT INTO connector_sessions (user_id, provider, session_token, user_email, status, token_info) "
            "VALUES ('alice', 'google_drive', 'tok-a', 'alice@example.com', 'authorized', "
            "CAST(:ti AS jsonb)) RETURNING id"
        ),
        {"ti": json.dumps({"access_token": "at", "refresh_token": "rt"})},
    ).scalar()
    ids["mcp"] = conn.execute(
        text(
            "INSERT INTO connector_sessions (user_id, provider, server_url, session_data) "
            "VALUES ('alice', 'mcp:https://mcp.example.com', 'https://mcp.example.com', CAST(:sd AS jsonb)) "
            "RETURNING id"
        ),
        {"sd": json.dumps({"tokens": {"access_token": "m"}})},
    ).scalar()
    ids["source"] = conn.execute(
        text(
            "INSERT INTO sources (user_id, name, type, remote_data) "
            "VALUES ('alice', 'Handbook', 'connector:file', CAST(:rd AS jsonb)) RETURNING id"
        ),
        {"rd": json.dumps({"provider": "google_drive", "file_ids": ["f1"]})},
    ).scalar()
    ids["other_source"] = conn.execute(
        text(
            "INSERT INTO sources (user_id, name, type, remote_data) "
            "VALUES ('bob', 'Bob files', 'connector:file', CAST(:rd AS jsonb)) RETURNING id"
        ),
        {"rd": json.dumps({"provider": "google_drive"})},
    ).scalar()
    ids["mcp_tool"] = conn.execute(
        text(
            "INSERT INTO user_tools (user_id, name, config) "
            "VALUES ('alice', 'mcp_tool', CAST(:c AS jsonb)) RETURNING id"
        ),
        {"c": json.dumps({"server_url": "https://mcp.example.com/mcp", "auth_type": "oauth"})},
    ).scalar()
    ids["bearer_tool"] = conn.execute(
        text(
            "INSERT INTO user_tools (user_id, name, config) "
            "VALUES ('alice', 'mcp_tool', CAST(:c AS jsonb)) RETURNING id"
        ),
        {"c": json.dumps({"server_url": "https://mcp.example.com/mcp", "auth_type": "bearer"})},
    ).scalar()
    return ids


class TestMigration0040:
    def test_head_has_connection_columns(self, pg_engine):
        with pg_engine.connect() as conn:
            assert {"connector_key", "display_name", "account_label", "auth_kind", "updated_at"} <= _columns(
                conn, "connector_sessions"
            )
            assert "connection_id" in _columns(conn, "sources")
            assert "connection_id" in _columns(conn, "user_tools")
            assert {"connector_key", "enabled", "credential_mode"} <= _columns(conn, "connector_policies")

    def test_backfill_links_legacy_rows(self, pg_engine):
        url = pg_engine.url.render_as_string(hide_password=False)
        _run_alembic(url, "downgrade", _0037)
        with pg_engine.begin() as conn:
            ids = _seed_legacy(conn)
        _run_alembic(url, "upgrade", "head")

        with pg_engine.connect() as conn:
            drive = conn.execute(
                text(
                    "SELECT connector_key, auth_kind, display_name, account_label "
                    "FROM connector_sessions WHERE id = :id"
                ),
                {"id": ids["drive"]},
            ).one()
            assert tuple(drive) == ("google_drive", "oauth", "Google Drive", "alice@example.com")

            mcp = conn.execute(
                text("SELECT connector_key, auth_kind, display_name FROM connector_sessions WHERE id = :id"),
                {"id": ids["mcp"]},
            ).one()
            assert tuple(mcp) == ("custom_mcp", "mcp_oauth", "mcp.example.com")

            linked = conn.execute(
                text("SELECT connection_id FROM sources WHERE id = :id"), {"id": ids["source"]}
            ).scalar()
            assert linked == ids["drive"]
            # Bob has no session for the provider: nothing to link.
            assert (
                conn.execute(
                    text("SELECT connection_id FROM sources WHERE id = :id"), {"id": ids["other_source"]}
                ).scalar()
                is None
            )
            tool = conn.execute(
                text("SELECT connection_id FROM user_tools WHERE id = :id"), {"id": ids["mcp_tool"]}
            ).scalar()
            assert tool == ids["mcp"]
            # A bearer MCP tool has no OAuth session to point at.
            bearer = conn.execute(
                text("SELECT connection_id FROM user_tools WHERE id = :id"), {"id": ids["bearer_tool"]}
            ).scalar()
            assert bearer is None

    def test_downgrade_then_upgrade_is_idempotent(self, pg_engine):
        url = pg_engine.url.render_as_string(hide_password=False)
        _run_alembic(url, "downgrade", _0037)
        with pg_engine.connect() as conn:
            assert "connector_key" not in _columns(conn, "connector_sessions")
            assert "connection_id" not in _columns(conn, "sources")
        _run_alembic(url, "upgrade", "head")
        _run_alembic(url, "downgrade", _0037)
        _run_alembic(url, "upgrade", "head")
        with pg_engine.connect() as conn:
            assert "connector_key" in _columns(conn, "connector_sessions")
            assert "connection_id" in _columns(conn, "user_tools")


def _seed_secrets(conn) -> dict:
    """Plaintext tokens and v1 tool secrets, as a pre-0040 install stored them."""
    from docsgpt.security.encryption import encrypt_credentials

    ids = {}
    ids["drive"] = conn.execute(
        text(
            "INSERT INTO connector_sessions (user_id, provider, session_token, user_email, status, token_info) "
            "VALUES ('carol', 'google_drive', 'tok-c', 'carol@example.com', 'authorized', CAST(:ti AS jsonb)) "
            "RETURNING id"
        ),
        {"ti": json.dumps({"access_token": "plain-at", "refresh_token": "plain-rt", "scopes": ["drive"]})},
    ).scalar()
    ids["mcp"] = conn.execute(
        text(
            "INSERT INTO connector_sessions (user_id, provider, server_url, session_data) "
            "VALUES ('carol', 'mcp:https://mcp.notion.com', 'https://mcp.notion.com', CAST(:sd AS jsonb)) "
            "RETURNING id"
        ),
        {"sd": json.dumps({
            "tokens": {"access_token": "mcp-at", "refresh_token": "mcp-rt"},
            "client_info": {"client_id": "cid", "client_secret": "dcr-secret"},
            "other": 1,
        })},
    ).scalar()
    ids["mcp_pending"] = conn.execute(
        text(
            "INSERT INTO connector_sessions (user_id, provider, server_url, session_data) "
            "VALUES ('carol', 'mcp:https://half.example.com', 'https://half.example.com', CAST(:sd AS jsonb)) "
            "RETURNING id"
        ),
        {"sd": json.dumps({"client_info": {"client_id": "x"}})},
    ).scalar()
    for name, token in (("telegram_a", "111111:AAAAAAAA"), ("telegram_b", "111111:AAAAAAAA")):
        ids[name] = conn.execute(
            text("INSERT INTO user_tools (user_id, name, config) VALUES ('carol', 'telegram', CAST(:c AS jsonb)) "
                 "RETURNING id"),
            {"c": json.dumps({"encrypted_credentials": encrypt_credentials({"token": token}, "carol")})},
        ).scalar()
    ids["mcp_key_tool"] = conn.execute(
        text("INSERT INTO user_tools (user_id, name, config) VALUES ('carol', 'mcp_tool', CAST(:c AS jsonb)) "
             "RETURNING id"),
        {"c": json.dumps({
            "server_url": "https://tools.example.com/mcp", "auth_type": "bearer",
            "encrypted_credentials": encrypt_credentials({"bearer_token": "bearer-secret-9999"}, "carol"),
        })},
    ).scalar()
    ids["mcp_oauth_tool"] = conn.execute(
        text("INSERT INTO user_tools (user_id, name, config) VALUES ('carol', 'mcp_tool', CAST(:c AS jsonb)) "
             "RETURNING id"),
        {"c": json.dumps({"server_url": "https://mcp.notion.com/mcp", "auth_type": "oauth"})},
    ).scalar()
    return ids


class TestMigration0040Credentials:
    def _upgrade_with(self, pg_engine, seed):
        url = pg_engine.url.render_as_string(hide_password=False)
        _run_alembic(url, "downgrade", _0037)
        with pg_engine.begin() as conn:
            ids = seed(conn)
        _run_alembic(url, "upgrade", "head")
        return url, ids

    def test_tokens_are_encrypted_and_plaintext_removed(self, pg_engine):
        from docsgpt.connectors.service import read_secrets

        _, ids = self._upgrade_with(pg_engine, _seed_secrets)
        with pg_engine.connect() as conn:
            rows = {
                r.id: dict(r._mapping)
                for r in conn.execute(text("SELECT * FROM connector_sessions WHERE user_id = 'carol'"))
            }
            dump = json.dumps([
                {k: v for k, v in r.items() if k not in ("encrypted_credentials",)} for r in rows.values()
            ], default=str)
        # Nothing readable is left outside the envelope.
        for secret in ("plain-at", "plain-rt", "mcp-at", "mcp-rt", "dcr-secret", "AAAAAAAA", "bearer-secret"):
            assert secret not in dump
        drive = rows[ids["drive"]]
        assert drive["token_info"] is None
        assert drive["has_refresh_token"] is True
        assert drive["scopes"] == ["drive"]
        assert drive["status"] == "connected"
        assert read_secrets(drive)["token_info"]["refresh_token"] == "plain-rt"
        mcp = rows[ids["mcp"]]
        assert mcp["session_data"] == {"other": 1}
        assert mcp["status"] == "connected"
        assert read_secrets(mcp)["client_info"]["client_secret"] == "dcr-secret"
        assert rows[ids["mcp_pending"]]["status"] == "pending"

    def test_api_key_tools_share_one_connection(self, pg_engine):
        from docsgpt.connectors.service import read_secrets

        _, ids = self._upgrade_with(pg_engine, _seed_secrets)
        with pg_engine.connect() as conn:
            links = dict(conn.execute(
                text("SELECT id, connection_id FROM user_tools WHERE user_id = 'carol'")
            ).fetchall())
            assert links[ids["telegram_a"]] is not None
            assert links[ids["telegram_a"]] == links[ids["telegram_b"]]
            telegram = dict(conn.execute(
                text("SELECT * FROM connector_sessions WHERE id = :i"), {"i": links[ids["telegram_a"]]}
            ).one()._mapping)
            assert telegram["auth_kind"] == "api_key"
            assert telegram["account_label"] == "…AAAA"
            assert read_secrets(telegram) == {"credentials": {"token": "111111:AAAAAAAA"}}
            bearer = dict(conn.execute(
                text("SELECT * FROM connector_sessions WHERE id = :i"), {"i": links[ids["mcp_key_tool"]]}
            ).one()._mapping)
            assert (bearer["connector_key"], bearer["server_url"]) == ("custom_mcp", "https://tools.example.com")
            # Rollback safety: the tool keeps its v1 copy for a release.
            config = conn.execute(
                text("SELECT config FROM user_tools WHERE id = :i"), {"i": ids["telegram_a"]}
            ).scalar()
            assert "encrypted_credentials" in config

    def test_different_keys_with_the_same_hint_get_their_own_connections(self, pg_engine):
        from docsgpt.connectors.service import read_secrets
        from docsgpt.security.encryption import encrypt_credentials

        def seed(conn):
            ids = {}
            for name, token in (("a", "111111:SAMEEND1"), ("b", "222222:SAMEEND1")):
                ids[name] = conn.execute(
                    text("INSERT INTO user_tools (user_id, name, config) VALUES ('frank', 'telegram', "
                         "CAST(:c AS jsonb)) RETURNING id"),
                    {"c": json.dumps({"encrypted_credentials": encrypt_credentials({"token": token}, "frank")})},
                ).scalar()
            return ids

        _, ids = self._upgrade_with(pg_engine, seed)
        with pg_engine.connect() as conn:
            links = dict(conn.execute(
                text("SELECT id, connection_id FROM user_tools WHERE user_id = 'frank'")
            ).fetchall())
            assert links[ids["a"]] != links[ids["b"]]
            for name, token in (("a", "111111:SAMEEND1"), ("b", "222222:SAMEEND1")):
                row = dict(conn.execute(
                    text("SELECT * FROM connector_sessions WHERE id = :i"), {"i": links[ids[name]]}
                ).one()._mapping)
                assert read_secrets(row) == {"credentials": {"token": token}}

    def test_oauth_mcp_tools_keep_member_credentials(self, pg_engine):
        _, ids = self._upgrade_with(pg_engine, _seed_secrets)
        with pg_engine.connect() as conn:
            modes = dict(conn.execute(
                text("SELECT id, credential_mode FROM user_tools WHERE user_id = 'carol'")
            ).fetchall())
        assert modes[ids["mcp_oauth_tool"]] == "member"
        assert modes[ids["telegram_a"]] == "owner"

    def test_multiple_accounts_per_provider_allowed(self, pg_engine):
        with pg_engine.begin() as conn:
            for label in ("a@example.com", "b@example.com"):
                conn.execute(
                    text("INSERT INTO connector_sessions (user_id, provider, account_label, status) "
                         "VALUES ('dan', 'google_drive', :l, 'connected')"),
                    {"l": label},
                )
        with pg_engine.connect() as conn:
            assert conn.execute(
                text("SELECT count(*) FROM connector_sessions WHERE user_id = 'dan'")
            ).scalar() == 2

    def test_downgrade_restores_plaintext(self, pg_engine):
        url, ids = self._upgrade_with(pg_engine, _seed_secrets)
        _run_alembic(url, "downgrade", _0037)
        with pg_engine.connect() as conn:
            token_info = conn.execute(
                text("SELECT token_info FROM connector_sessions WHERE id = :i"), {"i": ids["drive"]}
            ).scalar()
            session_data = conn.execute(
                text("SELECT session_data FROM connector_sessions WHERE id = :i"), {"i": ids["mcp"]}
            ).scalar()
            api_rows = conn.execute(
                text("SELECT count(*) FROM connector_sessions WHERE provider = 'telegram'")
            ).scalar()
        assert token_info["refresh_token"] == "plain-rt"
        assert session_data["tokens"]["access_token"] == "mcp-at"
        assert api_rows == 0
        _run_alembic(url, "upgrade", "head")

    def test_downgrade_keeps_secrets_of_tools_made_after_upgrade(self, pg_engine):
        from docsgpt.security.encryption import decrypt_credentials, encrypt_json

        url, _ = self._upgrade_with(pg_engine, _seed_secrets)
        # A tool added through the wizard keeps its key only on the connection.
        with pg_engine.begin() as conn:
            connection_id = conn.execute(
                text(
                    "INSERT INTO connector_sessions (user_id, provider, connector_key, auth_kind, status, "
                    "account_label, encrypted_credentials, session_data) VALUES ('erin', 'ntfy', 'ntfy', "
                    "'api_key', 'connected', '…9999', :blob, '{}'::jsonb) RETURNING id"
                ),
                {"blob": encrypt_json({"credentials": {"token": "ntfy-secret-9999"}}, "erin")},
            ).scalar()
            tool_id = conn.execute(
                text("INSERT INTO user_tools (user_id, name, config, connection_id) "
                     "VALUES ('erin', 'ntfy', CAST(:c AS jsonb), :cid) RETURNING id"),
                {"c": json.dumps({"server_url": "https://ntfy.sh"}), "cid": connection_id},
            ).scalar()
        _run_alembic(url, "downgrade", _0037)
        with pg_engine.connect() as conn:
            config = conn.execute(text("SELECT config FROM user_tools WHERE id = :i"), {"i": tool_id}).scalar()
        assert config["server_url"] == "https://ntfy.sh"
        assert decrypt_credentials(config["encrypted_credentials"], "erin") == {"token": "ntfy-secret-9999"}
        _run_alembic(url, "upgrade", "head")
        with pg_engine.connect() as conn:
            relinked = conn.execute(
                text("SELECT connection_id FROM user_tools WHERE id = :i"), {"i": tool_id}
            ).scalar()
        assert relinked is not None

    def test_second_upgrade_is_a_no_op(self, pg_engine):
        from docsgpt.connectors.service import read_secrets

        url, ids = self._upgrade_with(pg_engine, _seed_secrets)
        _run_alembic(url, "downgrade", _0037)
        _run_alembic(url, "upgrade", "head")
        with pg_engine.connect() as conn:
            drive = dict(conn.execute(
                text("SELECT * FROM connector_sessions WHERE id = :i"), {"i": ids["drive"]}
            ).one()._mapping)
            count = conn.execute(
                text("SELECT count(*) FROM connector_sessions WHERE provider = 'telegram'")
            ).scalar()
        assert read_secrets(drive)["token_info"]["access_token"] == "plain-at"
        assert count == 1


def test_model_metadata_matches_the_policy_and_custom_model_columns():
    """The SQLAlchemy tables mirror the migrations for both ``enabled`` columns."""
    from docsgpt.storage.db.models import connector_policies_table, user_custom_models_table

    policy_enabled = connector_policies_table.c.enabled
    assert policy_enabled.nullable is True and policy_enabled.server_default is None
    model_enabled = user_custom_models_table.c.enabled
    assert model_enabled.nullable is False
    assert str(model_enabled.server_default.arg) == "true"
