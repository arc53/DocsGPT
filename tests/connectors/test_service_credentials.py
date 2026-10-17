"""Tests for connection credentials: storage, refresh, failure handling."""

from __future__ import annotations

import json
import threading
import time
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import text

from docsgpt.connectors import service
from docsgpt.security.encryption import encrypt_json


def _patch_service_db(conn):
    @contextmanager
    def _yield():
        yield conn

    return patch.multiple("docsgpt.connectors.service", db_session=_yield, db_readonly=_yield)


def _connection(conn, *, user="alice", provider="google_drive", secrets=None, status="connected", **extra) -> str:
    cols = {
        "user_id": user,
        "provider": provider,
        "connector_key": provider,
        "auth_kind": extra.pop("auth_kind", "oauth"),
        "status": status,
        "account_label": extra.pop("account_label", f"{user}@example.com"),
        "encrypted_credentials": encrypt_json(secrets, user) if secrets is not None else None,
        **extra,
    }
    names = ", ".join(cols)
    values = ", ".join(f":{k}" for k in cols)
    return str(
        conn.execute(
            text(f"INSERT INTO connector_sessions ({names}) VALUES ({values}) RETURNING id"), cols,
        ).scalar()
    )


def _source(conn, connection_id, user="alice") -> str:
    return str(
        conn.execute(
            text(
                "INSERT INTO sources (user_id, name, type, connection_id) "
                "VALUES (:u, 'Docs', 'connector:file', CAST(:c AS uuid)) RETURNING id"
            ),
            {"u": user, "c": connection_id},
        ).scalar()
    )


def _row(conn, connection_id):
    from docsgpt.storage.db.repositories.connector_sessions import ConnectorSessionsRepository

    return ConnectorSessionsRepository(conn).get(connection_id)


class _FakeAuth:
    """A provider whose refresh rotates the refresh token on every call."""

    def __init__(self, *, expired=True, fail=None, delay=0.0):
        self.expired = expired
        self.fail = fail
        self.delay = delay
        self.calls = []
        self._lock = threading.Lock()

    def is_token_expired(self, token_info):
        return self.expired and token_info.get("access_token") == "old-at"

    def refresh_access_token(self, refresh_token):
        with self._lock:
            self.calls.append(refresh_token)
            n = len(self.calls)
        if self.delay:
            time.sleep(self.delay)
        if self.fail:
            raise self.fail
        if refresh_token != "rt-0":
            # A reused rotating refresh token is rejected, like Microsoft's.
            raise ValueError("invalid_grant: refresh token already used")
        return {"access_token": f"new-at-{n}", "refresh_token": f"rt-{n}", "expiry": None}

    def sanitize_token_info(self, token_info, **extra):
        return {k: token_info.get(k) for k in ("access_token", "refresh_token", "expiry", "cloud_id")}


def _auth(fake):
    return patch("docsgpt.parser.connectors.connector_creator.ConnectorCreator.create_auth", return_value=fake)


class TestSecrets:
    def test_write_and_read(self, pg_conn):
        cid = _connection(pg_conn, secrets=None, status="pending")
        service.write_secrets(pg_conn, _row(pg_conn, cid), {"token_info": {"access_token": "a", "refresh_token": "r"}})
        row = _row(pg_conn, cid)
        assert row["token_info"] is None
        assert row["has_refresh_token"] is True
        assert "access_token" not in json.dumps(row["session_data"])
        assert service.read_secrets(row) == {"token_info": {"access_token": "a", "refresh_token": "r"}}

    def test_legacy_plaintext_is_read(self, pg_conn):
        from docsgpt.storage.db.repositories.connector_sessions import ConnectorSessionsRepository

        row = ConnectorSessionsRepository(pg_conn).upsert(
            "alice", "share_point", token_info={"access_token": "p"}, status="authorized",
        )
        assert service.read_secrets(row)["token_info"]["access_token"] == "p"

    def test_decrypt_failure_flags_reconnect(self, pg_conn):
        cid = _connection(pg_conn, secrets={"token_info": {"access_token": "a"}})
        pg_conn.execute(
            text("UPDATE connector_sessions SET encrypted_credentials = 'v2:ffffffff:AAAA' WHERE id = CAST(:i AS uuid)"),
            {"i": cid},
        )
        with _patch_service_db(pg_conn), patch("docsgpt.events.publisher.publish_user_event"):
            assert service.load_secrets(_row(pg_conn, cid)) is None
        row = _row(pg_conn, cid)
        assert row["status"] == "reconnect_needed"
        assert row["last_error"] == service.DECRYPT_ERROR


class TestGetValidTokenInfo:
    def test_returns_unexpired_token(self, pg_conn):
        cid = _connection(pg_conn, secrets={"token_info": {"access_token": "fresh", "refresh_token": "rt-0"}})
        fake = _FakeAuth(expired=True)
        with _patch_service_db(pg_conn), _auth(fake):
            info = service.get_valid_token_info(cid)
        assert info["access_token"] == "fresh"
        assert fake.calls == []

    def test_refreshes_and_persists_rotated_token(self, pg_conn):
        cid = _connection(pg_conn, secrets={"token_info": {"access_token": "old-at", "refresh_token": "rt-0"}})
        fake = _FakeAuth()
        with _patch_service_db(pg_conn), _auth(fake):
            info = service.get_valid_token_info(cid)
        assert info["access_token"] == "new-at-1"
        stored = service.read_secrets(_row(pg_conn, cid))["token_info"]
        assert stored["refresh_token"] == "rt-1"

    def test_rejected_access_token_forces_refresh(self, pg_conn):
        cid = _connection(pg_conn, secrets={"token_info": {"access_token": "fresh", "refresh_token": "rt-0"}})
        fake = _FakeAuth(expired=False)
        with _patch_service_db(pg_conn), _auth(fake):
            info = service.get_valid_token_info(cid, rejected_access_token="fresh")
        assert info["access_token"] == "new-at-1"

    def test_rejected_token_already_replaced_is_not_refreshed_again(self, pg_conn):
        cid = _connection(pg_conn, secrets={"token_info": {"access_token": "newer", "refresh_token": "rt-0"}})
        fake = _FakeAuth(expired=False)
        with _patch_service_db(pg_conn), _auth(fake):
            info = service.get_valid_token_info(cid, rejected_access_token="stale")
        assert info["access_token"] == "newer"
        assert fake.calls == []

    def test_revoked_grant_pauses_sources_and_notifies(self, pg_conn):
        cid = _connection(pg_conn, secrets={"token_info": {"access_token": "old-at", "refresh_token": "rt-0"}})
        source = _source(pg_conn, cid)
        fake = _FakeAuth(fail=ValueError("Error refreshing token: invalid_grant"))
        with _patch_service_db(pg_conn), _auth(fake), patch(
            "docsgpt.events.publisher.publish_user_event"
        ) as publish:
            with pytest.raises(service.ConnectionUnavailable):
                service.get_valid_token_info(cid)
        assert _row(pg_conn, cid)["status"] == "reconnect_needed"
        meta = pg_conn.execute(
            text("SELECT metadata FROM sources WHERE id = CAST(:i AS uuid)"), {"i": source}
        ).scalar()
        assert meta["sync_state"] == "paused_reconnect"
        publish.assert_called_once()
        assert publish.call_args.args[1] == "connection.reconnect_needed"
        # The toast says what stopped working.
        assert publish.call_args.args[2]["source_count"] == 1
        assert publish.call_args.args[2]["tool_count"] == 0
        # No account data or secrets in the event.
        assert "alice@example.com" not in json.dumps(publish.call_args.args[2])

    def test_second_failure_does_not_notify_again(self, pg_conn):
        cid = _connection(pg_conn, secrets={"token_info": {"access_token": "old-at", "refresh_token": "rt-0"}})
        fake = _FakeAuth(fail=ValueError("invalid_grant"))
        with _patch_service_db(pg_conn), _auth(fake), patch(
            "docsgpt.events.publisher.publish_user_event"
        ) as publish:
            for _ in range(2):
                with pytest.raises(service.ConnectionUnavailable):
                    service.get_valid_token_info(cid)
        assert publish.call_count == 1

    def test_transient_failure_keeps_status(self, pg_conn):
        import requests

        cid = _connection(pg_conn, secrets={"token_info": {"access_token": "old-at", "refresh_token": "rt-0"}})
        fake = _FakeAuth(fail=requests.exceptions.ConnectionError("network down"))
        with _patch_service_db(pg_conn), _auth(fake):
            with pytest.raises(service.TransientConnectionError):
                service.get_valid_token_info(cid)
        assert _row(pg_conn, cid)["status"] == "connected"

    def test_disconnected_connection_is_unavailable(self, pg_conn):
        cid = _connection(pg_conn, secrets={}, status="disconnected")
        with _patch_service_db(pg_conn):
            with pytest.raises(service.ConnectionUnavailable) as exc:
                service.get_valid_token_info(cid)
        assert exc.value.status == "disconnected"

    def test_concurrent_refresh_spends_the_refresh_token_once(self, pg_engine):
        """Two workers with an expiring rotating token: one refresh, both succeed."""
        with pg_engine.begin() as conn:
            cid = _connection(conn, secrets={"token_info": {"access_token": "old-at", "refresh_token": "rt-0"}})

        @contextmanager
        def _session():
            with pg_engine.begin() as conn:
                yield conn

        fake = _FakeAuth(delay=0.3)
        results, errors = [], []

        def worker():
            try:
                results.append(service.get_valid_token_info(cid)["access_token"])
            except Exception as exc:  # pragma: no cover - reported below
                errors.append(exc)

        with patch.multiple("docsgpt.connectors.service", db_session=_session, db_readonly=_session), _auth(fake):
            threads = [threading.Thread(target=worker) for _ in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
        assert errors == []
        assert fake.calls == ["rt-0"]
        assert results == ["new-at-1", "new-at-1"]


class TestApiKeyConnections:
    def test_create_and_reuse(self, pg_conn):
        from docsgpt.connectors import catalog

        telegram = catalog.get_definition("telegram")
        row, created = service.create_api_key_connection(pg_conn, "alice", telegram, {"token": "123456:ABCDEFG"})
        assert created is True
        assert row["account_label"] == "…DEFG"
        assert row["status"] == "connected"
        again, created = service.create_api_key_connection(pg_conn, "alice", telegram, {"token": "123456:ABCDEFG"})
        assert created is False and again["id"] == row["id"]
        assert service.get_credentials(again) == {"token": "123456:ABCDEFG"}

    def test_different_keys_with_the_same_hint_stay_apart(self, pg_conn):
        """Two keys ending in the same four characters are two accounts, not one."""
        from docsgpt.connectors import catalog

        postgres = catalog.get_definition("postgres")
        first, _ = service.create_api_key_connection(
            pg_conn, "alice", postgres, {"token": "postgresql://ro@db-a/app"},
        )
        second, created = service.create_api_key_connection(
            pg_conn, "alice", postgres, {"token": "postgresql://rw@db-b/app"},
        )
        assert created is True and second["id"] != first["id"]
        assert second["account_label"] != first["account_label"]
        assert service.get_credentials(_row(pg_conn, str(first["id"]))) == {"token": "postgresql://ro@db-a/app"}
        again, created = service.create_api_key_connection(
            pg_conn, "alice", postgres, {"token": "postgresql://rw@db-b/app"},
        )
        assert created is False and again["id"] == second["id"]

    def test_same_label_different_key_does_not_overwrite(self, pg_conn):
        from docsgpt.connectors import catalog

        brave = catalog.get_definition("brave")
        first, _ = service.create_api_key_connection(pg_conn, "alice", brave, {"token": "key-one-111111"}, label="Team")
        second, created = service.create_api_key_connection(
            pg_conn, "alice", brave, {"token": "key-two-222222"}, label="Team",
        )
        assert created is True and second["id"] != first["id"]
        assert service.get_credentials(_row(pg_conn, str(first["id"]))) == {"token": "key-one-111111"}

    def test_missing_field(self, pg_conn):
        from docsgpt.connectors import catalog

        with pytest.raises(ValueError):
            service.create_api_key_connection(pg_conn, "alice", catalog.get_definition("telegram"), {})

    def test_default_key_refused_with_auth(self, pg_conn, monkeypatch):
        from docsgpt.connectors import catalog
        from docsgpt.core.settings import settings
        from docsgpt.security.encryption import DEFAULT_ENCRYPTION_KEY

        monkeypatch.setattr(settings, "ENCRYPTION_SECRET_KEY", DEFAULT_ENCRYPTION_KEY)
        monkeypatch.setattr(settings, "AUTH_TYPE", "session_jwt")
        with pytest.raises(service.EncryptionKeyNotConfigured):
            service.create_api_key_connection(
                pg_conn, "alice", catalog.get_definition("brave"), {"token": "secret-key-1234"},
            )

    def test_disabled_connector_refused_before_other_errors(self, pg_conn, monkeypatch):
        from docsgpt.connectors import catalog
        from docsgpt.core.settings import settings
        from docsgpt.security.encryption import DEFAULT_ENCRYPTION_KEY
        from docsgpt.storage.db.repositories.connector_policies import ConnectorPoliciesRepository

        monkeypatch.setattr(settings, "ENCRYPTION_SECRET_KEY", DEFAULT_ENCRYPTION_KEY)
        monkeypatch.setattr(settings, "AUTH_TYPE", "session_jwt")
        ConnectorPoliciesRepository(pg_conn).upsert("telegram", enabled=False)
        telegram = catalog.get_definition("telegram")
        # Callers fall back to a legacy per-tool secret on these other errors.
        for credentials in ({"token": "123456:ABCDEFG"}, {}):
            with pytest.raises(service.ConnectorDisabled):
                service.create_api_key_connection(pg_conn, "alice", telegram, credentials)

    def test_default_key_allowed_single_user(self, pg_conn, monkeypatch):
        from docsgpt.connectors import catalog
        from docsgpt.core.settings import settings
        from docsgpt.security.encryption import DEFAULT_ENCRYPTION_KEY

        monkeypatch.setattr(settings, "ENCRYPTION_SECRET_KEY", DEFAULT_ENCRYPTION_KEY)
        monkeypatch.setattr(settings, "AUTH_TYPE", None)
        row, _ = service.create_api_key_connection(
            pg_conn, "local", catalog.get_definition("brave"), {"token": "secret-key-1234"},
        )
        assert row["encrypted_credentials"].startswith("v2:")

    def test_flagged_connection_credentials_unavailable(self, pg_conn):
        cid = _connection(
            pg_conn, provider="telegram", auth_kind="api_key", status="reconnect_needed",
            secrets={"credentials": {"token": "t"}},
        )
        with pytest.raises(service.ConnectionUnavailable):
            service.get_credentials(_row(pg_conn, cid))


class TestOAuthCompletion:
    def test_new_account(self, pg_conn):
        state_row = service.begin_oauth(pg_conn, "alice", "google_drive")
        assert state_row["status"] == "pending"
        row = service.complete_oauth(pg_conn, state_row, "google_drive", {"access_token": "a"}, "a@example.com")
        assert row["id"] == state_row["id"]
        assert row["account_label"] == "a@example.com"
        assert row["status"] == "connected"
        assert row["session_token"]

    def test_same_account_updates_existing_connection(self, pg_conn):
        first = service.complete_oauth(
            pg_conn, service.begin_oauth(pg_conn, "alice", "google_drive"), "google_drive",
            {"access_token": "a"}, "a@example.com",
        )
        source = _source(pg_conn, str(first["id"]))
        pg_conn.execute(
            text("UPDATE connector_sessions SET status = 'reconnect_needed' WHERE id = CAST(:i AS uuid)"),
            {"i": str(first["id"])},
        )
        pg_conn.execute(
            text("UPDATE sources SET metadata = '{\"sync_state\": \"paused_reconnect\"}' WHERE id = CAST(:i AS uuid)"),
            {"i": source},
        )
        pending = service.begin_oauth(pg_conn, "alice", "google_drive")
        again = service.complete_oauth(pg_conn, pending, "google_drive", {"access_token": "b"}, "a@example.com")
        assert again["id"] == first["id"]
        assert again["status"] == "connected"
        assert _row(pg_conn, str(pending["id"])) is None
        meta = pg_conn.execute(
            text("SELECT metadata FROM sources WHERE id = CAST(:i AS uuid)"), {"i": source}
        ).scalar()
        assert "sync_state" not in meta

    def test_second_account_is_a_second_connection(self, pg_conn):
        first = service.complete_oauth(
            pg_conn, service.begin_oauth(pg_conn, "alice", "google_drive"), "google_drive",
            {"access_token": "a"}, "a@example.com",
        )
        second = service.complete_oauth(
            pg_conn, service.begin_oauth(pg_conn, "alice", "google_drive"), "google_drive",
            {"access_token": "b"}, "b@example.com",
        )
        assert first["id"] != second["id"]
        assert len(service.list_connections(pg_conn, "alice")) == 2

    def test_reconnect_as_the_same_account_heals_the_connection(self, pg_conn):
        cid = _connection(pg_conn, status="reconnect_needed", secrets={"token_info": {"access_token": "old"}},
                          account_label="a@example.com")
        state_row = service.begin_oauth(pg_conn, "alice", "google_drive", cid)
        row = service.complete_oauth(pg_conn, state_row, "google_drive", {"access_token": "new"}, "a@example.com")
        assert str(row["id"]) == cid
        assert row["status"] == "connected"

    def test_reconnect_as_another_account_leaves_the_connection_alone(self, pg_conn):
        cid = _connection(pg_conn, status="reconnect_needed", secrets={"token_info": {"access_token": "old"}},
                          account_label="a@example.com")
        source = _source(pg_conn, cid)
        pg_conn.execute(
            text("UPDATE sources SET metadata = '{\"sync_state\": \"paused_reconnect\"}' WHERE id = CAST(:i AS uuid)"),
            {"i": source},
        )
        state_row = service.begin_oauth(pg_conn, "alice", "google_drive", cid)
        row = service.complete_oauth(pg_conn, state_row, "google_drive", {"access_token": "b"}, "b@example.com")
        assert str(row["id"]) != cid
        assert row["account_label"] == "b@example.com"
        assert row["status"] == "connected"
        original = _row(pg_conn, cid)
        assert original["account_label"] == "a@example.com"
        assert original["user_email"] != "b@example.com"
        assert original["status"] == "reconnect_needed"
        assert service.read_secrets(original)["token_info"]["access_token"] == "old"
        meta = pg_conn.execute(
            text("SELECT metadata FROM sources WHERE id = CAST(:i AS uuid)"), {"i": source}
        ).scalar()
        assert meta["sync_state"] == "paused_reconnect"

    def test_reconnect_must_name_own_connection(self, pg_conn):
        cid = _connection(pg_conn, user="bob", secrets={})
        with pytest.raises(service.ConnectionUnavailable):
            service.begin_oauth(pg_conn, "alice", "google_drive", cid)


class TestReencrypt:
    def test_rewrites_rows_on_previous_key(self, pg_conn, monkeypatch):
        from docsgpt.core.settings import settings
        from docsgpt.security.encryption import current_key_id, envelope_key_id

        monkeypatch.setattr(settings, "ENCRYPTION_SECRET_KEY", "old-key")
        cid = _connection(pg_conn, secrets={"token_info": {"access_token": "a"}})
        monkeypatch.setattr(settings, "ENCRYPTION_SECRET_KEY", "new-key")
        monkeypatch.setattr(settings, "ENCRYPTION_SECRET_KEY_PREVIOUS", "old-key")
        with _patch_service_db(pg_conn):
            counts = service.reencrypt_all()
        assert counts == {"rewritten": 1, "current": 0, "failed": 0}
        row = _row(pg_conn, cid)
        assert envelope_key_id(row["encrypted_credentials"]) == current_key_id()
        monkeypatch.setattr(settings, "ENCRYPTION_SECRET_KEY_PREVIOUS", None)
        assert service.read_secrets(row)["token_info"]["access_token"] == "a"

    def test_unreadable_rows_flagged(self, pg_conn, monkeypatch):
        from docsgpt.core.settings import settings

        monkeypatch.setattr(settings, "ENCRYPTION_SECRET_KEY", "lost-key")
        cid = _connection(pg_conn, secrets={"token_info": {"access_token": "a"}})
        monkeypatch.setattr(settings, "ENCRYPTION_SECRET_KEY", "new-key")
        with _patch_service_db(pg_conn), patch("docsgpt.events.publisher.publish_user_event"):
            counts = service.reencrypt_all()
        assert counts["failed"] == 1
        assert _row(pg_conn, cid)["status"] == "reconnect_needed"


class TestReencryptSavedSecrets:
    """Secrets saved on tools and custom models, outside connections (v1 blobs)."""

    def _tool(self, conn, config, user="alice") -> str:
        return str(conn.execute(
            text(
                "INSERT INTO user_tools (user_id, name, config) VALUES (:u, 'api_tool', CAST(:c AS jsonb)) "
                "RETURNING id"
            ),
            {"u": user, "c": json.dumps(config)},
        ).scalar())

    def _model(self, conn, blob, user="alice") -> str:
        return str(conn.execute(
            text(
                "INSERT INTO user_custom_models (user_id, upstream_model_id, display_name, base_url, "
                "api_key_encrypted) VALUES (:u, 'm', 'M', 'https://api.example.com/v1', :b) RETURNING id"
            ),
            {"u": user, "b": blob},
        ).scalar())

    def _config(self, conn, tool_id) -> dict:
        return conn.execute(
            text("SELECT config FROM user_tools WHERE id = CAST(:i AS uuid)"), {"i": tool_id}
        ).scalar()

    def test_rewrites_tool_and_custom_model_secrets_so_the_previous_key_can_go(self, pg_conn, monkeypatch):
        from docsgpt.core.settings import settings
        from docsgpt.security.encryption import decrypt_credentials, encrypt_credentials

        monkeypatch.setattr(settings, "ENCRYPTION_SECRET_KEY", "old-key")
        tool = self._tool(pg_conn, {
            "server_url": "https://mcp.example.com",
            "encrypted_credentials": encrypt_credentials({"api_key": "t"}, "alice"),
            "encrypted_action_secrets": encrypt_credentials({"get": {"headers": {"X": "s"}}}, "alice"),
        })
        model = self._model(pg_conn, encrypt_credentials({"api_key": "m"}, "alice"))
        monkeypatch.setattr(settings, "ENCRYPTION_SECRET_KEY", "new-key")
        monkeypatch.setattr(settings, "ENCRYPTION_SECRET_KEY_PREVIOUS", "old-key")

        with _patch_service_db(pg_conn):
            counts = service.reencrypt_saved_secrets()

        assert counts == {"rewritten": 3, "current": 0, "failed": 0}
        monkeypatch.setattr(settings, "ENCRYPTION_SECRET_KEY_PREVIOUS", None)
        config = self._config(pg_conn, tool)
        assert config["server_url"] == "https://mcp.example.com"
        assert decrypt_credentials(config["encrypted_credentials"], "alice") == {"api_key": "t"}
        assert decrypt_credentials(config["encrypted_action_secrets"], "alice") == {"get": {"headers": {"X": "s"}}}
        blob = pg_conn.execute(
            text("SELECT api_key_encrypted FROM user_custom_models WHERE id = CAST(:i AS uuid)"), {"i": model}
        ).scalar()
        assert decrypt_credentials(blob, "alice") == {"api_key": "m"}

    def test_a_second_run_changes_nothing(self, pg_conn, monkeypatch):
        from docsgpt.core.settings import settings
        from docsgpt.security.encryption import encrypt_credentials

        monkeypatch.setattr(settings, "ENCRYPTION_SECRET_KEY", "old-key")
        tool = self._tool(pg_conn, {"encrypted_credentials": encrypt_credentials({"api_key": "t"}, "alice")})
        monkeypatch.setattr(settings, "ENCRYPTION_SECRET_KEY", "new-key")
        monkeypatch.setattr(settings, "ENCRYPTION_SECRET_KEY_PREVIOUS", "old-key")
        with _patch_service_db(pg_conn):
            service.reencrypt_saved_secrets()
            after_first = self._config(pg_conn, tool)
            counts = service.reencrypt_saved_secrets()
        assert counts == {"rewritten": 0, "current": 1, "failed": 0}
        assert self._config(pg_conn, tool) == after_first

    def test_unreadable_secrets_are_counted_and_left_untouched(self, pg_conn, monkeypatch):
        from docsgpt.core.settings import settings
        from docsgpt.security.encryption import encrypt_credentials

        monkeypatch.setattr(settings, "ENCRYPTION_SECRET_KEY", "lost-key")
        blob = encrypt_credentials({"api_key": "t"}, "alice")
        tool = self._tool(pg_conn, {"encrypted_credentials": blob})
        model = self._model(pg_conn, blob)
        monkeypatch.setattr(settings, "ENCRYPTION_SECRET_KEY", "new-key")
        monkeypatch.setattr(settings, "ENCRYPTION_SECRET_KEY_PREVIOUS", "old-key")

        with _patch_service_db(pg_conn):
            counts = service.reencrypt_saved_secrets()

        assert counts == {"rewritten": 0, "current": 0, "failed": 2}
        assert self._config(pg_conn, tool)["encrypted_credentials"] == blob
        assert pg_conn.execute(
            text("SELECT api_key_encrypted FROM user_custom_models WHERE id = CAST(:i AS uuid)"), {"i": model}
        ).scalar() == blob


class TestRemove:
    def test_keep_sources_delete_tools(self, pg_conn):
        cid = _connection(pg_conn, provider="telegram", auth_kind="api_key", secrets={"credentials": {"token": "t"}})
        source = _source(pg_conn, cid)
        pg_conn.execute(
            text(
                "INSERT INTO user_tools (user_id, name, connection_id) VALUES ('alice', 'telegram', CAST(:c AS uuid))"
            ),
            {"c": cid},
        )
        with patch("docsgpt.connectors.service.revoke_at_provider") as revoke:
            to_delete = service.remove_connection(pg_conn, _row(pg_conn, cid))
        assert to_delete == []
        revoke.assert_called_once()
        assert _row(pg_conn, cid) is None
        assert pg_conn.execute(text("SELECT count(*) FROM user_tools WHERE user_id = 'alice'")).scalar() == 0
        kept = pg_conn.execute(
            text("SELECT connection_id, sync_frequency FROM sources WHERE id = CAST(:i AS uuid)"), {"i": source}
        ).one()
        assert kept.connection_id is None and kept.sync_frequency == "never"

    def test_deleted_tools_leave_no_sharing_rows(self, pg_conn):
        from docsgpt.api.user.resource_access import set_settings
        from docsgpt.storage.db.repositories.user_tool_preferences import UserToolPreferencesRepository

        cid = _connection(pg_conn, provider="telegram", auth_kind="api_key", secrets={"credentials": {"token": "t"}})
        tool_id = str(pg_conn.execute(
            text(
                "INSERT INTO user_tools (user_id, name, connection_id) "
                "VALUES ('alice', 'telegram', CAST(:c AS uuid)) RETURNING id"
            ),
            {"c": cid},
        ).scalar())
        set_settings(pg_conn, "tool", tool_id, {"editors_can_share": True}, "alice")
        UserToolPreferencesRepository(pg_conn).set_in_chat("bob", tool_id, True)
        with patch("docsgpt.connectors.service.revoke_at_provider"):
            service.remove_connection(pg_conn, _row(pg_conn, cid))
        for table, column in (("resource_share_settings", "resource_id"), ("user_tool_preferences", "tool_id")):
            count = pg_conn.execute(
                text(f"SELECT count(*) FROM {table} WHERE {column} = CAST(:i AS uuid)"), {"i": tool_id}
            ).scalar()
            assert count == 0, table

    def test_delete_sources_returns_them(self, pg_conn):
        cid = _connection(pg_conn, secrets={})
        source = _source(pg_conn, cid)
        with patch("docsgpt.connectors.service.revoke_at_provider"):
            to_delete = service.remove_connection(pg_conn, _row(pg_conn, cid), sources="delete")
        assert [str(s["id"]) for s in to_delete] == [source]


class TestRevoke:
    def test_google_revocation_posts_token(self):
        response = MagicMock(status_code=200)
        with patch("requests.post", return_value=response) as post:
            ok = service.revoke_at_provider(
                {"provider": "google_drive"}, {"token_info": {"refresh_token": "rt", "access_token": "at"}},
            )
        assert ok
        assert post.call_args.kwargs["data"] == {"token": "rt"}

    def test_other_providers_are_local_only(self):
        with patch("requests.post") as post:
            assert not service.revoke_at_provider({"provider": "share_point"}, {"token_info": {"access_token": "a"}})
        post.assert_not_called()

    def test_failure_never_raises(self):
        import requests

        with patch("requests.post", side_effect=requests.exceptions.Timeout()):
            assert not service.revoke_at_provider({"provider": "google_drive"}, {"token_info": {"access_token": "a"}})


class TestMcpConnectionScope:
    def _mcp(self, conn, user="alice", base="https://mcp.notion.com"):
        return _connection(
            conn, user=user, provider=f"mcp:{base}", auth_kind="mcp_oauth", server_url=base,
            secrets={"tokens": {"access_token": f"{user}-mcp-token"}},
        )

    def test_reads_tokens_of_the_named_connection(self, pg_conn):
        cid = self._mcp(pg_conn)
        with _patch_service_db(pg_conn):
            data = service.read_mcp_secrets("alice", "https://mcp.notion.com", cid)
        assert data["tokens"]["access_token"] == "alice-mcp-token"

    def test_connection_for_another_server_yields_nothing(self, pg_conn):
        """A connection id never sends its tokens to a different server."""
        cid = self._mcp(pg_conn)
        with _patch_service_db(pg_conn):
            assert service.read_mcp_secrets("alice", "https://attacker.example", cid) == {}

    def test_writes_never_land_on_another_servers_connection(self, pg_conn):
        cid = self._mcp(pg_conn)
        with _patch_service_db(pg_conn):
            with pytest.raises(service.ConnectionUnavailable):
                service.update_mcp_secrets(
                    "alice", "https://attacker.example", {"tokens": {"access_token": "planted"}}, connection_id=cid,
                )
            assert service.read_mcp_secrets("alice", "https://mcp.notion.com", cid)["tokens"]["access_token"] == (
                "alice-mcp-token"
            )
            assert service.read_mcp_secrets("alice", "https://attacker.example") == {}

    def test_a_removed_connection_is_not_brought_back_by_a_late_token_write(self, pg_conn):
        """A client or sync still running when its connection is removed may
        renew the tokens afterwards; that must not re-create the connection."""
        cid = self._mcp(pg_conn)
        with _patch_service_db(pg_conn):
            service.remove_connection(pg_conn, service.ConnectorSessionsRepository(pg_conn).get(cid))
            with pytest.raises(service.ConnectionUnavailable):
                service.update_mcp_secrets(
                    "alice", "https://mcp.notion.com", {"tokens": {"access_token": "renewed"}}, connection_id=cid,
                )
            assert service.read_mcp_secrets("alice", "https://mcp.notion.com") == {}

    def test_removing_a_connection_forgets_its_cached_mcp_clients(self, pg_conn):
        import docsgpt.api.user  # noqa: F401  (loads mcp_tool without the circular import)
        from docsgpt.agents.tools import mcp_tool

        cid = self._mcp(pg_conn)
        mcp_tool._mcp_clients_cache.update({
            f"https://mcp.notion.com/mcp#http#oauth:{cid}:DocsGPT:none:cb": {"client": object(), "created_at": 0},
            "https://mcp.notion.com/mcp#http#oauth:alice:DocsGPT:none:cb": {"client": object(), "created_at": 0},
            "https://mcp.notion.com/mcp#http#oauth:bob:DocsGPT:none:cb": {"client": object(), "created_at": 0},
        })
        try:
            with _patch_service_db(pg_conn):
                service.remove_connection(pg_conn, service.ConnectorSessionsRepository(pg_conn).get(cid))
            keys = [k for k in mcp_tool._mcp_clients_cache if "mcp.notion.com" in k]
            assert keys == ["https://mcp.notion.com/mcp#http#oauth:bob:DocsGPT:none:cb"]
        finally:
            mcp_tool._mcp_clients_cache.clear()

    def test_mcp_routes_drop_client_supplied_connection_id(self):
        """Only the tool executor may pick the connection whose tokens a tool uses."""
        from docsgpt.api.user.tools.mcp import _sanitize_mcp_transport

        config = {"transport_type": "http", "connection_id": "someone-elses-connection"}
        _sanitize_mcp_transport(config)
        assert "connection_id" not in config

    def test_mcp_policy_check_fails_closed_when_unreadable(self):
        """A server whose admin switch cannot be read is not contacted."""
        from flask import Flask

        from docsgpt.api.user.tools import mcp as mcp_routes

        def _broken():
            raise RuntimeError("database is down")

        with Flask(__name__).app_context(), patch.object(mcp_routes, "db_readonly", _broken):
            resp = mcp_routes._mcp_policy_error({"server_url": "https://mcp.linear.app/mcp"})
        assert resp is not None and resp.status_code == 503
