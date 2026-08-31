"""Which embedding model an installation is pinned to."""

from unittest.mock import MagicMock, patch

import pytest

from application.storage.db import embeddings_pin
from application.storage.db.embeddings_pin import (
    NOTICE_KEY,
    PIN_KEY,
    resolve_embeddings_pin,
)
from application.vectorstore.model_registry import DEFAULT_LEGACY, DEFAULT_NEW_INSTALL


@pytest.fixture
def store():
    """An in-memory stand-in for the ``app_metadata`` key/value table."""
    data = {}
    repo = MagicMock()
    repo.get.side_effect = data.get
    repo.set.side_effect = lambda k, v: data.__setitem__(k, v)
    repo.setdefault.side_effect = lambda k, v: data.setdefault(k, v)
    repo._data = data
    return repo


def _run(store, *, has_sources, env_pinned=False, name="unset"):
    session = MagicMock()
    session.__enter__ = MagicMock(return_value=MagicMock())
    session.__exit__ = MagicMock(return_value=False)
    fields = {"EMBEDDINGS_NAME"} if env_pinned else set()
    with patch.object(embeddings_pin.settings, "EMBEDDINGS_NAME", name), patch.object(
        type(embeddings_pin.settings), "model_fields_set", property(lambda self: fields)
    ), patch.object(embeddings_pin, "db_session", return_value=session), patch.object(
        embeddings_pin, "AppMetadataRepository", return_value=store
    ), patch.object(
        embeddings_pin, "_has_sources", return_value=has_sources
    ):
        resolve_embeddings_pin()
        return embeddings_pin.settings.EMBEDDINGS_NAME


class TestFreshInstall:
    def test_an_empty_installation_is_pinned_to_the_current_model(self, store):
        assert _run(store, has_sources=False) == DEFAULT_NEW_INSTALL
        assert store._data[PIN_KEY] == DEFAULT_NEW_INSTALL

    def test_no_legacy_notice_is_printed(self, store, capsys):
        _run(store, has_sources=False)
        assert "reembed" not in capsys.readouterr().out
        assert NOTICE_KEY not in store._data


class TestExistingInstall:
    """An index built by the old model must keep being read by it."""

    def test_an_installation_with_sources_is_pinned_to_the_legacy_model(self, store):
        assert _run(store, has_sources=True) == DEFAULT_LEGACY
        assert store._data[PIN_KEY] == DEFAULT_LEGACY

    def test_the_notice_names_the_migration_command(self, store, capsys):
        _run(store, has_sources=True)
        out = capsys.readouterr().out
        assert "application.scripts.reembed" in out
        assert DEFAULT_NEW_INSTALL in out

    def test_the_notice_is_shown_only_once(self, store, capsys):
        _run(store, has_sources=True)
        capsys.readouterr()
        store._data.pop(PIN_KEY)  # force the decision again
        _run(store, has_sources=True)
        assert "reembed" not in capsys.readouterr().out


class TestPrecedence:
    def test_a_stored_pin_survives_new_sources(self, store):
        store._data[PIN_KEY] = DEFAULT_NEW_INSTALL
        assert _run(store, has_sources=True) == DEFAULT_NEW_INSTALL

    def test_the_environment_wins_and_nothing_is_stored(self, store):
        assert _run(store, has_sources=True, env_pinned=True, name="my/model") == "my/model"
        assert store._data == {}

    def test_an_unreachable_database_leaves_the_default_alone(self):
        with patch.object(embeddings_pin.settings, "EMBEDDINGS_NAME", "fallback"), patch.object(
            type(embeddings_pin.settings), "model_fields_set", property(lambda self: set())
        ), patch.object(embeddings_pin, "db_session", side_effect=OSError("no db")):
            resolve_embeddings_pin()
            assert embeddings_pin.settings.EMBEDDINGS_NAME == "fallback"


class TestSourceModelMismatch:
    """The only signal that an index is being queried by the wrong model."""

    def _run(self, rows, active, log):
        conn = MagicMock()
        conn.execute.side_effect = [
            MagicMock(scalar=MagicMock(return_value="sources")),
            MagicMock(fetchall=MagicMock(return_value=rows)),
        ]
        session = MagicMock()
        session.__enter__ = MagicMock(return_value=conn)
        session.__exit__ = MagicMock(return_value=False)
        with patch.object(embeddings_pin.settings, "EMBEDDINGS_NAME", active), patch.object(
            embeddings_pin, "db_session", return_value=session
        ):
            embeddings_pin.warn_on_source_model_mismatch(log)

    def test_a_different_model_is_reported_with_counts(self):
        log = MagicMock()
        self._run([(DEFAULT_LEGACY, 28)], DEFAULT_NEW_INSTALL, log)
        message = log.warning.call_args.args[0] % log.warning.call_args.args[1:]
        assert "28 built with" in message
        assert "application.scripts.reembed" in message

    def test_an_alias_is_not_a_mismatch(self):
        """A stored alias and the canonical name are the same model."""
        log = MagicMock()
        self._run([("sentence-transformers/all-mpnet-base-v2", 28)], DEFAULT_LEGACY, log)
        log.warning.assert_not_called()

    def test_a_matching_model_says_nothing(self):
        log = MagicMock()
        self._run([(DEFAULT_NEW_INSTALL, 5)], DEFAULT_NEW_INSTALL, log)
        log.warning.assert_not_called()

    def test_two_unregistered_names_that_differ_are_a_mismatch(self):
        log = MagicMock()
        self._run([("some/other-model", 3)], "my/custom-model", log)
        log.warning.assert_called_once()
