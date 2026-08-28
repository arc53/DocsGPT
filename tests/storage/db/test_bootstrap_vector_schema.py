"""Boot-time ownership of the pgvector schema.

``PGVectorStore`` used to run its DDL on every instantiation — once per source
per request. The schema is created here instead, once per process, and the boot
hook is also the only place that can catch an embedding-dimension mismatch:
a ``documents`` table built for a different model silently retrieves garbage.
"""

from __future__ import annotations

import ast
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from application.storage.db.bootstrap import ensure_vector_schema

_APP_PY = Path(__file__).resolve().parents[3] / "application" / "app.py"


@pytest.fixture
def vector_settings(monkeypatch):
    """Settings configured for a pgvector deployment."""
    from application.core import settings as settings_module

    settings = settings_module.settings
    monkeypatch.setattr(settings, "VECTOR_STORE", "pgvector", raising=False)
    monkeypatch.setattr(
        settings,
        "PGVECTOR_CONNECTION_STRING",
        "postgresql://user:pass@localhost/db",
        raising=False,
    )
    monkeypatch.setattr(settings, "GRAPHRAG_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "EMBEDDINGS_NAME", "test-model", raising=False)
    return settings


def _embeddings(dimension):
    stub = MagicMock()
    stub.dimension = dimension
    return stub


@pytest.mark.unit
class TestEnsureVectorSchemaSkips:
    def test_skips_when_the_store_is_not_pgvector(self, vector_settings, monkeypatch):
        monkeypatch.setattr(vector_settings, "VECTOR_STORE", "faiss", raising=False)

        with patch("psycopg.connect") as connect:
            ensure_vector_schema()

        connect.assert_not_called()

    def test_skips_when_no_connection_string_is_configured(
        self, vector_settings, monkeypatch
    ):
        monkeypatch.setattr(
            vector_settings, "PGVECTOR_CONNECTION_STRING", None, raising=False
        )
        monkeypatch.setattr(vector_settings, "POSTGRES_URI", None, raising=False)

        with patch("psycopg.connect") as connect:
            ensure_vector_schema()

        connect.assert_not_called()


@pytest.mark.unit
class TestEnsureVectorSchemaCreates:
    def _run(self, dimension=768, table_dimension=768):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        with patch("psycopg.connect", return_value=conn) as connect, patch(
            "application.vectorstore.model_registry.dimension_for",
            return_value=dimension,
        ), patch(
            "application.vectorstore.pgvector.PGVectorStore.create_schema"
        ) as vector_schema, patch(
            "application.vectorstore.pgvector.PGVectorStore.table_dimension",
            return_value=table_dimension,
        ), patch(
            "application.graphrag.store.GraphStore.create_schema"
        ) as graph_schema, patch(
            "application.vectorstore.pgvector._pool_for"
        ) as pool_for:
            ensure_vector_schema()
        return connect, conn, cursor, vector_schema, graph_schema, pool_for

    def test_creates_the_vector_schema_under_the_advisory_lock(self, vector_settings):
        connect, conn, cursor, vector_schema, graph_schema, _ = self._run()

        # A bounded connect: an unreachable or suspended vector DB must fail the
        # hook, not hang boot until a liveness probe kills the process.
        connect.assert_called_once_with(
            "postgresql://user:pass@localhost/db", connect_timeout=10
        )
        statements = " ".join(str(c) for c in cursor.execute.call_args_list)
        assert "pg_advisory_xact_lock" in statements
        vector_schema.assert_called_once()
        assert vector_schema.call_args.kwargs["dimension"] == 768
        graph_schema.assert_not_called()
        conn.commit.assert_called_once()
        conn.close.assert_called_once()

    def test_creates_the_graph_schema_only_when_graphrag_is_enabled(
        self, vector_settings, monkeypatch
    ):
        monkeypatch.setattr(vector_settings, "GRAPHRAG_ENABLED", True, raising=False)

        _, _, _, _, graph_schema, _ = self._run()

        graph_schema.assert_called_once()
        assert graph_schema.call_args.kwargs["dimension"] == 768

    def test_uses_a_direct_connection_never_the_store_pool(self, vector_settings):
        # The hook can run pre-fork under ``gunicorn --preload``; a pooled
        # socket inherited by a worker is a corrupted connection.
        _, _, _, _, _, pool_for = self._run()

        pool_for.assert_not_called()


@pytest.mark.unit
class TestEnsureVectorSchemaDimensionCheck:
    def test_raises_when_the_table_width_disagrees_with_the_model(
        self, vector_settings
    ):
        conn = MagicMock()
        with patch("psycopg.connect", return_value=conn), patch(
            "application.vectorstore.model_registry.dimension_for",
            return_value=1536,
        ), patch("application.vectorstore.pgvector.PGVectorStore.create_schema"), patch(
            "application.vectorstore.pgvector.PGVectorStore.table_dimension",
            return_value=768,
        ):
            with pytest.raises(RuntimeError) as excinfo:
                ensure_vector_schema()

        message = str(excinfo.value)
        assert "768" in message and "1536" in message
        assert "test-model" in message
        conn.close.assert_called_once()

    def test_skips_the_check_when_the_embeddings_expose_no_dimension(
        self, vector_settings
    ):
        conn = MagicMock()
        stub = MagicMock()
        del stub.dimension
        with patch("psycopg.connect", return_value=conn), patch(
            "application.vectorstore.base.get_embeddings", return_value=stub
        ), patch(
            "application.vectorstore.pgvector.PGVectorStore.create_schema"
        ) as vector_schema, patch(
            "application.vectorstore.pgvector.PGVectorStore.table_dimension",
            return_value=1536,
        ):
            ensure_vector_schema()  # must not raise

        assert vector_schema.call_args.kwargs["dimension"] == 768

    def test_skips_the_check_when_the_model_cannot_be_loaded(self, vector_settings):
        conn = MagicMock()
        with patch("psycopg.connect", return_value=conn), patch(
            "application.vectorstore.base.get_embeddings",
            side_effect=RuntimeError("no model"),
        ), patch(
            "application.vectorstore.pgvector.PGVectorStore.create_schema"
        ) as vector_schema, patch(
            "application.vectorstore.pgvector.PGVectorStore.table_dimension",
            return_value=1536,
        ):
            ensure_vector_schema()  # must not raise

        assert vector_schema.call_args.kwargs["dimension"] == 768


@pytest.mark.unit
class TestBootGating:
    """The boot hook must stay behind AUTO_VECTOR_SCHEMA.

    Asserted on the source because importing ``application.app`` runs the hook,
    and a test that imports it cannot observe the gate it just executed.
    """

    def test_app_calls_the_hook_behind_the_setting(self):
        source = _APP_PY.read_text()

        assert "if settings.AUTO_VECTOR_SCHEMA:" in source
        assert "ensure_vector_schema(" in source

    def test_the_boot_hook_cannot_take_the_process_down(self):
        """A vector-DB fault must degrade retrieval, not crash-loop the app.

        The hook runs at import time, so an exception escaping it stops
        gunicorn and every Celery worker from booting -- taking auth, chat
        history and webhooks down with retrieval. ``PGVectorStore`` re-checks
        the schema on its write path, so failing soft here loses nothing.
        """
        tree = ast.parse(_APP_PY.read_text())

        def _calls_hook(node) -> bool:
            return any(
                isinstance(n, ast.Call)
                and isinstance(n.func, ast.Name)
                and n.func.id == "ensure_vector_schema"
                for n in ast.walk(node)
            )

        assert any(
            isinstance(node, ast.Try) and node.handlers and _calls_hook(node)
            for node in ast.walk(tree)
        ), "ensure_vector_schema() at import time must be wrapped in try/except"

    def test_setting_defaults_on(self):
        from application.core.settings import Settings

        assert Settings.model_fields["AUTO_VECTOR_SCHEMA"].default is True

    def test_test_suite_opts_out_by_default(self):
        conftest = Path(__file__).resolve().parents[2] / "conftest.py"

        assert 'os.environ.setdefault("AUTO_VECTOR_SCHEMA", "false")' in (
            conftest.read_text()
        )


@pytest.mark.unit
class TestBootDoesNotLoadTheModel:
    """The hook needs an integer, not an inference session.

    It used to build the embeddings instance to read ``.dimension`` off it,
    loading several hundred MB of ONNX into every API and worker process at
    import. For a model the registry describes that is a lookup.
    """

    def _run(self, registry_dim, loader):
        conn = MagicMock()
        conn.cursor.return_value = MagicMock()
        with patch("psycopg.connect", return_value=conn), patch(
            "application.vectorstore.model_registry.dimension_for",
            return_value=registry_dim,
        ), patch(
            "application.vectorstore.base.build_local_embeddings", loader
        ), patch(
            "application.vectorstore.pgvector.PGVectorStore.create_schema"
        ) as vector_schema, patch(
            "application.vectorstore.pgvector.PGVectorStore.table_dimension",
            return_value=None,
        ):
            ensure_vector_schema()
        return vector_schema

    def test_a_registered_model_is_never_constructed(self, vector_settings):
        loader = MagicMock()
        vector_schema = self._run(768, loader)
        loader.assert_not_called()
        assert vector_schema.call_args.kwargs["dimension"] == 768

    def test_an_unregistered_model_still_falls_back_to_loading(self, vector_settings):
        loader = MagicMock(return_value=_embeddings(1024))
        vector_schema = self._run(None, loader)
        loader.assert_called_once()
        assert vector_schema.call_args.kwargs["dimension"] == 1024


@pytest.mark.unit
class TestUnknownWidthIsProbed:
    """A remote server's width is only knowable by asking it.

    ``RemoteEmbeddings`` reports ``None`` until its first call, so sizing the
    table from the attribute alone fell back to 768 and skipped the mismatch
    check — the silent ``vector(768)`` column this hook exists to prevent.
    """

    def _run(self, remote, table_dimension=1024):
        conn = MagicMock()
        conn.cursor.return_value = MagicMock()
        with patch("psycopg.connect", return_value=conn), patch(
            "application.vectorstore.model_registry.dimension_for", return_value=None
        ), patch(
            "application.vectorstore.base.build_local_embeddings", return_value=remote
        ), patch(
            "application.vectorstore.pgvector.PGVectorStore.create_schema"
        ) as vector_schema, patch(
            "application.vectorstore.pgvector.PGVectorStore.table_dimension",
            return_value=table_dimension,
        ):
            try:
                ensure_vector_schema()
                raised = False
            except RuntimeError:
                raised = True
        return vector_schema, raised

    @staticmethod
    def _remote(width=None, error=None):
        remote = MagicMock()
        remote.dimension = None
        remote.embed_query.side_effect = error or (lambda _text: [0.0] * width)
        return remote

    def test_the_table_is_sized_from_the_probe(self, vector_settings):
        remote = self._remote(width=1024)
        vector_schema, _ = self._run(remote, table_dimension=1024)
        remote.embed_query.assert_called_once()
        assert vector_schema.call_args.kwargs["dimension"] == 1024

    def test_the_probe_restores_the_mismatch_check(self, vector_settings):
        _, raised = self._run(self._remote(width=768), table_dimension=1024)
        assert raised, "a 768-dim model against a vector(1024) table must fail loudly"

    def test_an_unreachable_server_does_not_block_boot(self, vector_settings):
        vector_schema, raised = self._run(
            self._remote(error=ConnectionError("server down")), table_dimension=1024
        )
        assert not raised
        assert vector_schema.call_args.kwargs["dimension"] == 768

    def test_a_model_that_knows_its_width_is_not_probed(self, vector_settings):
        local = MagicMock()
        local.dimension = 384
        vector_schema, _ = self._run(local, table_dimension=384)
        local.embed_query.assert_not_called()
        assert vector_schema.call_args.kwargs["dimension"] == 384
