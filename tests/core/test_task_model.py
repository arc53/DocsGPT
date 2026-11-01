"""The task model: which model runs DocsGPT's own jobs (drafter, graph extraction, monitor judge)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from docsgpt.core import model_utils
from docsgpt.core.settings import settings
from docsgpt.storage.db import model_defaults
from docsgpt.storage.db.repositories.users import UsersRepository

BUILTIN = {"gpt-a", "gpt-b", "gpt-env"}
CUSTOM = {"alice": {"byom-alice"}}
DISABLED = {"gpt-off"}


def _registry(default="gpt-default"):
    """A registry knowing ``BUILTIN`` (plus a disabled one) and Alice's own ``byom-alice``."""

    def get_model(model_id, user_id=None):
        if user_id and model_id in CUSTOM.get(user_id, set()):
            return SimpleNamespace(id=model_id, enabled=True, source="user")
        if model_id in BUILTIN or model_id == default:
            return SimpleNamespace(id=model_id, enabled=True, source="builtin")
        if model_id in DISABLED:
            return SimpleNamespace(id=model_id, enabled=False, source="builtin")
        return None

    return SimpleNamespace(
        get_model=get_model,
        model_exists=lambda model_id, user_id=None: get_model(model_id, user_id) is not None,
        default_model_id=default,
    )


@pytest.fixture(autouse=True)
def registry(monkeypatch):
    reg = _registry()
    monkeypatch.setattr("docsgpt.core.model_registry.ModelRegistry.get_instance", lambda: reg)
    monkeypatch.setattr(settings, "TASK_MODEL_ID", None)
    return reg


def _stored(user=None, instance=None):
    return patch.object(model_utils, "_stored_task_models", return_value=(user, instance))


@pytest.mark.unit
class TestResolverOrder:
    def test_nothing_set_is_the_default_model(self):
        with _stored():
            assert model_utils.get_task_model_id("alice") == "gpt-default"
            assert model_utils.get_task_model_id(None) == "gpt-default"

    def test_the_users_choice_wins(self, monkeypatch):
        monkeypatch.setattr(settings, "TASK_MODEL_ID", "gpt-env")
        with _stored(user="gpt-a", instance="gpt-b"):
            assert model_utils.get_task_model_id("alice") == "gpt-a"

    def test_a_user_may_pick_their_own_custom_model(self):
        with _stored(user="byom-alice", instance="gpt-b"):
            assert model_utils.get_task_model_id("alice") == "byom-alice"

    def test_someone_elses_custom_model_falls_through(self):
        # A stored id that only resolves under its owner never runs for another user.
        with _stored(user="byom-alice", instance="gpt-b"):
            assert model_utils.get_task_model_id("bob") == "gpt-b"

    def test_the_instance_default_comes_before_the_env(self, monkeypatch):
        monkeypatch.setattr(settings, "TASK_MODEL_ID", "gpt-env")
        with _stored(instance="gpt-b"):
            assert model_utils.get_task_model_id("alice") == "gpt-b"
            assert model_utils.get_task_model_id(None) == "gpt-b"

    def test_the_env_comes_before_the_default_model(self, monkeypatch):
        monkeypatch.setattr(settings, "TASK_MODEL_ID", "gpt-env")
        with _stored():
            assert model_utils.get_task_model_id("alice") == "gpt-env"

    def test_no_user_skips_the_users_choice(self):
        with _stored(user="gpt-a", instance="gpt-b"):
            assert model_utils.get_task_model_id(None) == "gpt-b"


@pytest.mark.unit
class TestFallthrough:
    @pytest.mark.parametrize("stale", ["gone-model", "gpt-off", "", "  "])
    def test_a_stale_user_choice_falls_through(self, stale):
        with _stored(user=stale, instance="gpt-b"):
            assert model_utils.get_task_model_id("alice") == "gpt-b"

    def test_a_custom_model_as_instance_default_is_ignored(self):
        # The instance default is built-in only: a custom id resolves for nobody here.
        with _stored(instance="byom-alice"):
            assert model_utils.get_task_model_id("alice") == "gpt-default"

    def test_a_stale_instance_default_falls_through(self, monkeypatch):
        monkeypatch.setattr(settings, "TASK_MODEL_ID", "gpt-env")
        with _stored(instance="gone-model"):
            assert model_utils.get_task_model_id("alice") == "gpt-env"

    def test_an_unknown_env_model_falls_through(self, monkeypatch):
        monkeypatch.setattr(settings, "TASK_MODEL_ID", "not-in-the-catalog")
        with _stored():
            assert model_utils.get_task_model_id("alice") == "gpt-default"

    def test_a_database_error_falls_through_to_the_env(self, monkeypatch):
        monkeypatch.setattr(settings, "TASK_MODEL_ID", "gpt-env")

        def broken():
            raise RuntimeError("database down")

        monkeypatch.setattr("docsgpt.storage.db.session.db_readonly", broken)
        assert model_utils.get_task_model_id("alice") == "gpt-env"

    def test_no_model_at_all_is_none(self, monkeypatch):
        monkeypatch.setattr(
            "docsgpt.core.model_registry.ModelRegistry.get_instance", lambda: _registry(default=None)
        )
        with _stored():
            assert model_utils.get_task_model_id("alice") is None


@pytest.mark.unit
class TestModelIsUsable:
    def test_usable(self):
        assert model_utils.model_is_usable("gpt-a")
        assert model_utils.model_is_usable("byom-alice", "alice")
        assert not model_utils.model_is_usable("byom-alice")
        assert not model_utils.model_is_usable("byom-alice", "bob")
        assert not model_utils.model_is_usable("gpt-off")
        assert not model_utils.model_is_usable("")
        assert not model_utils.model_is_usable(None)


@pytest.mark.unit
class TestStoredTaskModels:
    """One read returns the user's and the instance's stored choices."""

    def test_reads_both_in_one_go(self, pg_conn):
        UsersRepository(pg_conn).set_task_model_id("alice", "gpt-a")
        model_defaults.save_task_model(pg_conn, "gpt-b")
        assert model_defaults.stored_task_models(pg_conn, "alice") == ("gpt-a", "gpt-b")
        assert model_defaults.stored_task_models(pg_conn, "bob") == (None, "gpt-b")
        assert model_defaults.stored_task_models(pg_conn, None) == (None, "gpt-b")

    def test_nothing_stored(self, pg_conn):
        assert model_defaults.stored_task_models(pg_conn, "alice") == (None, None)
        assert model_defaults.stored_task_model(pg_conn) is None

    def test_clearing_the_instance_default(self, pg_conn):
        model_defaults.save_task_model(pg_conn, "gpt-b")
        assert model_defaults.save_task_model(pg_conn, None) is None
        assert model_defaults.stored_task_model(pg_conn) is None

    def test_an_unreadable_row_is_no_row(self, pg_conn):
        from docsgpt.storage.db.repositories.app_metadata import AppMetadataRepository

        AppMetadataRepository(pg_conn).set(model_defaults.KEY, "not json")
        assert model_defaults.stored_task_model(pg_conn) is None
        AppMetadataRepository(pg_conn).set(model_defaults.KEY, '["a list"]')
        assert model_defaults.stored_task_models(pg_conn, None) == (None, None)

    def test_the_user_setting_keeps_the_other_preferences(self, pg_conn):
        repo = UsersRepository(pg_conn)
        repo.set_chat_prompt_id("alice", "strict")
        repo.set_task_model_id("alice", "gpt-a")
        assert repo.get("alice")["tool_preferences"] == {"chat_prompt_id": "strict", "task_model_id": "gpt-a"}
        repo.set_task_model_id("alice", None)
        assert repo.get("alice")["tool_preferences"] == {"chat_prompt_id": "strict"}

    def test_the_resolver_reads_through_the_database(self, pg_conn, monkeypatch):
        from contextlib import contextmanager

        @contextmanager
        def readonly():
            yield pg_conn

        monkeypatch.setattr("docsgpt.storage.db.session.db_readonly", readonly)
        UsersRepository(pg_conn).set_task_model_id("alice", "gpt-a")
        model_defaults.save_task_model(pg_conn, "gpt-b")
        assert model_utils.get_task_model_id("alice") == "gpt-a"
        assert model_utils.get_task_model_id("bob") == "gpt-b"
