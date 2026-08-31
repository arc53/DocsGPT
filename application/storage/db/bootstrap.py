"""Self-bootstrapping database setup for the DocsGPT user-data Postgres DB.

On app startup the Flask factory (and Celery worker init) can call
:func:`ensure_database_ready` to:

1. Create the target database if it's missing (dev-friendly; requires the
   configured role to have ``CREATEDB`` privilege).
2. Apply every pending Alembic migration up to ``head``.

:func:`ensure_vector_schema` does the same job for the *vector* database
(``pgvector``): it owns the ``documents`` table and, when GraphRAG is on,
the graph tables, so the retrieval hot path never runs DDL. That database
may be a separate cluster, which is why it has no Alembic migration.

Every step is gated by a setting that defaults ON for dev convenience and
can be turned off in prod (``AUTO_CREATE_DB`` / ``AUTO_MIGRATE`` /
``AUTO_VECTOR_SCHEMA``) where schema is managed out-of-band by a deploy
pipeline.

All heavy imports (alembic, psycopg, sqlalchemy.exc sub-symbols) are
deferred to inside the function so merely importing this module has no
side effects and is cheap for test collection.
"""

from __future__ import annotations

import logging
import time
from typing import Optional


def ensure_database_ready(
    uri: Optional[str],
    *,
    create_db: bool,
    migrate: bool,
    logger: Optional[logging.Logger] = None,
) -> None:
    """Make sure the target Postgres DB exists and is migrated to ``head``.

    This is idempotent and safe to call once per process. Each step is
    independently gated so prod deployments that manage schema externally
    can disable the migrate step while still allowing the process to boot
    against an already-provisioned database.

    Args:
        uri: SQLAlchemy URI for the user-data Postgres database. If
            ``None`` or empty, the function logs and returns — the app
            supports running without a configured URI for certain dev
            flows that don't touch user data.
        create_db: If ``True``, auto-create the database when it's
            missing. Requires the configured role to have ``CREATEDB``.
        migrate: If ``True``, run ``alembic upgrade head`` after the
            database is reachable.
        logger: Optional logger to use. Defaults to this module's logger.

    Raises:
        Exception: Any failure in an explicitly-enabled step is re-raised
            so the app fails fast rather than booting into a broken state.
            Missing-role / auth errors surface cleanly without a
            mis-directed auto-create attempt.
    """
    log = logger or logging.getLogger(__name__)

    if not uri:
        log.info(
            "ensure_database_ready: POSTGRES_URI is not set; "
            "skipping database bootstrap."
        )
        return

    if create_db:
        _ensure_database_exists(uri, log)

    if migrate:
        _run_migrations(log)


def _release_boot_only_embeddings(log: logging.Logger) -> None:
    """Drop a model this hook loaded that the process will never use again.

    ``ensure_vector_schema`` has to run the model to learn the width of a model
    the registry does not describe. ``EmbeddingsSingleton`` then caches it for
    the life of the process -- correct when this process embeds, pure waste in
    an API that delegates every embed to the worker, where it costs ~400 MB for
    a small model and ~800 MB for a granite-sized one that is never called.

    Only the local-ONNX case is dropped. A ``RemoteEmbeddings`` is cheap and is
    exactly what the process goes on to use, and with delegation off the model
    would only be rebuilt on the first query.

    Bounds retention, not the transient peak: the load still happens, and the
    ONNX Runtime arena may not return every page to the OS.
    """
    from application.core.settings import settings

    if settings.EMBEDDINGS_BASE_URL:
        return
    if getattr(settings, "EMBEDDINGS_DELEGATE_TO_WORKER", False) is not True:
        return

    import gc

    from application.vectorstore.base import EmbeddingsSingleton

    if EmbeddingsSingleton._instances.pop(settings.EMBEDDINGS_NAME, None) is None:
        return
    gc.collect()
    log.info(
        "ensure_vector_schema: released the embeddings model loaded to read its "
        "width; this process delegates embedding to the worker and would never "
        "have used it."
    )


def ensure_vector_schema(*, logger: Optional[logging.Logger] = None) -> None:
    """Create the pgvector schema once at boot and verify its dimension.

    Owning the DDL here is what lets ``PGVectorStore`` construction stay free:
    the retriever builds one store per source per request, and each used to run
    ``CREATE EXTENSION`` / ``CREATE TABLE`` / two ``CREATE INDEX`` statements
    before its first SELECT. A dimension mismatch between the table and the
    configured embeddings model is fatal here rather than silent garbage
    retrieval at query time.

    Args:
        logger: Optional logger. Defaults to this module's logger.

    Raises:
        RuntimeError: The existing ``documents`` table was built for a
            different embedding width than the configured model produces.
        Exception: Any connection or DDL failure is re-raised so the app fails
            fast, matching :func:`ensure_database_ready`.
    """
    log = logger or logging.getLogger(__name__)

    from application.core.settings import settings

    store_kind = (settings.VECTOR_STORE or "").lower()
    if store_kind != "pgvector":
        log.debug(
            "ensure_vector_schema: VECTOR_STORE is %r, not pgvector; nothing to do.",
            settings.VECTOR_STORE,
        )
        return

    dsn = getattr(settings, "PGVECTOR_CONNECTION_STRING", None)
    if not dsn and getattr(settings, "POSTGRES_URI", None):
        from application.core.db_uri import normalize_pgvector_connection_string

        dsn = normalize_pgvector_connection_string(settings.POSTGRES_URI)
    if not dsn:
        log.info(
            "ensure_vector_schema: no pgvector connection string configured "
            "(PGVECTOR_CONNECTION_STRING / POSTGRES_URI); skipping."
        )
        return

    import psycopg

    from application.vectorstore.pgvector import (
        DEFAULT_EMBEDDING_DIM,
        SCHEMA_LOCK_KEY,
        PGVectorStore,
    )

    # All this needs is an integer, and for a model the registry describes that
    # is a lookup. It used to construct the embeddings instance, which loaded
    # ~800 MB of ONNX into every API and worker process at import purely to
    # read ``.dimension`` off it.
    from application.vectorstore.model_registry import dimension_for

    dim: Optional[int] = dimension_for(settings.EMBEDDINGS_NAME)

    graph_enabled = bool(getattr(settings, "GRAPHRAG_ENABLED", False))
    started = time.monotonic()
    # A plain connection, never the store's pool: this can run pre-fork under
    # ``gunicorn --preload``, and an inherited pooled socket is a broken one.
    # Bounded: a suspended/unreachable vector cluster must fail this hook
    # rather than hang boot until a liveness probe kills the process.
    conn = psycopg.connect(dsn, connect_timeout=10)
    try:
        cursor = conn.cursor()
        try:
            # Serialize concurrent workers; released when this transaction ends.
            cursor.execute(
                "SELECT pg_advisory_xact_lock(hashtext(%s));", (SCHEMA_LOCK_KEY,)
            )
        finally:
            cursor.close()

        if dim is None:
            # An unregistered model only reports its width once something has
            # run it. Build it in-process rather than through
            # ``get_embeddings``: at boot there is no Celery task in flight, so
            # a delegating client would dispatch to a worker that may not be up
            # yet. The width must come from the model and not from the existing
            # table -- reading the table would make the check below compare a
            # value against itself, which is how a model of a different width
            # silently inherits a table it does not fit.
            try:
                from application.vectorstore.base import build_local_embeddings

                embedding = build_local_embeddings()
                dim = getattr(embedding, "dimension", None)
                if not dim:
                    # A remote client knows nothing about its server until it
                    # has called it, so ask once. Without this the table is
                    # sized at the default and the check below is skipped --
                    # which is how a remote model of any other width silently
                    # got a vector(768) column, the exact failure this hook
                    # exists to catch. Milvus and Qdrant probe the same way.
                    dim = len(embedding.embed_query("dimension probe"))
            except Exception as exc:  # noqa: BLE001 — never block boot on the model
                log.warning(
                    "ensure_vector_schema: could not determine the embedding width "
                    "(%s); creating the table with %d dimensions and skipping the "
                    "dimension check.",
                    exc,
                    DEFAULT_EMBEDDING_DIM,
                )
            finally:
                _release_boot_only_embeddings(log)

        if dim is None:
            log.warning(
                "ensure_vector_schema: the embeddings model exposes no dimension; "
                "using %d and skipping the dimension check.",
                DEFAULT_EMBEDDING_DIM,
            )

        PGVectorStore.create_schema(conn, dimension=dim or DEFAULT_EMBEDDING_DIM)
        if graph_enabled:
            from application.graphrag.store import (
                DEFAULT_NAME_EMBEDDING_DIM,
                GraphStore,
            )

            GraphStore.create_schema(
                conn, dimension=dim or DEFAULT_NAME_EMBEDDING_DIM
            )
        conn.commit()

        actual = PGVectorStore.table_dimension(conn)
        if dim and actual and actual != dim:
            raise RuntimeError(
                f"pgvector table 'documents' has vector({actual}) but "
                f"EMBEDDINGS_NAME={settings.EMBEDDINGS_NAME} produces {dim}-dim "
                "vectors; re-ingest into a fresh table or point "
                "PGVECTOR_CONNECTION_STRING at the matching database."
            )

        log.info(
            "ensure_vector_schema: table 'documents' ready "
            "(dimension=%s, graph tables=%s) in %d ms.",
            actual or dim or DEFAULT_EMBEDDING_DIM,
            "yes" if graph_enabled else "no",
            int((time.monotonic() - started) * 1000),
        )
    except Exception as exc:
        try:
            conn.rollback()
        except Exception:
            # Connection already gone; nothing left to roll back.
            pass
        log.error("ensure_vector_schema: %s", exc)
        raise
    finally:
        conn.close()


def _ensure_database_exists(uri: str, log: logging.Logger) -> None:
    """Create the target database if a connection reveals it's missing.

    We probe with a lightweight ``connect().close()``. If Postgres
    reports ``InvalidCatalogName`` (SQLSTATE ``3D000``), we reconnect to
    the server's ``postgres`` maintenance DB and issue ``CREATE DATABASE``
    in AUTOCOMMIT mode (required — CREATE DATABASE can't run in a
    transaction). Any other connection failure (bad host, auth failure,
    missing role) is re-raised untouched so the operator sees the true
    cause instead of a mis-directed auto-create attempt.
    """
    # Lazy imports keep module import side-effect free.
    from sqlalchemy import create_engine
    from sqlalchemy.engine import make_url
    from sqlalchemy.exc import OperationalError

    url = make_url(uri)
    target_db = url.database
    if not target_db:
        raise RuntimeError(
            f"POSTGRES_URI is missing a database name: {uri!r}. "
            "Expected something like "
            "'postgresql+psycopg://user:pass@host:5432/docsgpt'."
        )

    probe_engine = create_engine(uri, pool_pre_ping=False)
    try:
        try:
            conn = probe_engine.connect()
        except OperationalError as exc:
            if _is_missing_database(exc):
                log.info(
                    "ensure_database_ready: database %r is missing; "
                    "creating it...",
                    target_db,
                )
                _create_database(url, target_db, log)
                log.info("ensure_database_ready: database %r ready.", target_db)
                return
            # Not a missing-DB error — surface it as-is. This is the path
            # for bad host/auth/role-missing, and auto-creating would be
            # actively wrong there.
            log.error(
                "ensure_database_ready: cannot connect to Postgres for "
                "database %r: %s",
                target_db,
                exc,
            )
            raise
        else:
            conn.close()
            log.info("ensure_database_ready: database %r ready.", target_db)
    finally:
        probe_engine.dispose()


def _create_database(url, target_db: str, log: logging.Logger) -> None:
    """Issue ``CREATE DATABASE`` against the server's ``postgres`` DB.

    Uses AUTOCOMMIT (required by Postgres — ``CREATE DATABASE`` cannot run
    inside a transaction). The database identifier is quoted via
    ``psycopg.sql.Identifier`` so unusual names (hyphens, reserved words)
    are handled correctly.

    Args:
        url: Parsed SQLAlchemy URL for the target DB; we reuse
            host/port/credentials and swap the database to ``postgres``.
        target_db: The target database name to create.
        log: Logger for INFO/ERROR breadcrumbs.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.exc import OperationalError, ProgrammingError

    # psycopg is imported lazily — its error classes are the canonical
    # cause markers Postgres hands us back.
    import psycopg
    from psycopg import sql as pg_sql

    maintenance_url = url.set(database="postgres")
    maintenance_engine = create_engine(
        maintenance_url,
        isolation_level="AUTOCOMMIT",
        pool_pre_ping=False,
    )
    try:
        with maintenance_engine.connect() as conn:
            # Use psycopg's Identifier to quote the DB name safely. The
            # SQL object renders as a literal ``CREATE DATABASE "<name>"``
            # which SQLAlchemy passes through to psycopg verbatim.
            stmt = pg_sql.SQL("CREATE DATABASE {}").format(
                pg_sql.Identifier(target_db)
            )
            raw = conn.connection.dbapi_connection  # psycopg connection
            with raw.cursor() as cur:
                try:
                    cur.execute(stmt)
                except psycopg.errors.DuplicateDatabase:
                    # Another worker won the race — benign.
                    log.info(
                        "ensure_database_ready: database %r already "
                        "created by a concurrent worker; continuing.",
                        target_db,
                    )
                except psycopg.errors.InsufficientPrivilege as exc:
                    log.error(
                        "ensure_database_ready: role lacks CREATEDB "
                        "privilege to create %r. Either GRANT CREATEDB "
                        "to the role, create the database manually, or "
                        "set AUTO_CREATE_DB=False and provision it "
                        "out-of-band. See docs/Deploying/Postgres-"
                        "Migration for guidance. Underlying error: %s",
                        target_db,
                        exc,
                    )
                    raise
    except (OperationalError, ProgrammingError) as exc:
        log.error(
            "ensure_database_ready: failed to create database %r: %s. "
            "See docs/Deploying/Postgres-Migration for manual setup.",
            target_db,
            exc,
        )
        raise
    finally:
        maintenance_engine.dispose()


def _is_missing_database(exc: Exception) -> bool:
    """Return True if ``exc`` indicates the target database doesn't exist.

    We check three signals in the cause chain:

    1. ``psycopg.errors.InvalidCatalogName`` — the canonical class for
       SQLSTATE ``3D000`` when raised during a query.
    2. ``pgcode`` / ``diag.sqlstate`` equal to ``3D000`` — defensive, for
       driver versions that surface the code on a generic class.
    3. The canonical server message phrasing ``database "..." does not
       exist`` — **required** for connection-time failures, because
       psycopg 3's ``OperationalError`` raised by ``connect()`` does NOT
       populate ``sqlstate`` (the connection never completed the protocol
       handshake, so the attributes stay ``None``). The server's error
       message itself is stable across Postgres versions, so this is a
       reliable fallback for the only case that matters: DB missing at
       boot.
    """
    try:
        import psycopg

        invalid_catalog = psycopg.errors.InvalidCatalogName
    except Exception:  # noqa: BLE001 — defensive; never break on import
        invalid_catalog = None

    seen: set[int] = set()
    cursor: Optional[BaseException] = exc
    while cursor is not None and id(cursor) not in seen:
        seen.add(id(cursor))
        if invalid_catalog is not None and isinstance(cursor, invalid_catalog):
            return True
        pgcode = getattr(cursor, "pgcode", None) or getattr(
            getattr(cursor, "diag", None), "sqlstate", None
        )
        if pgcode == "3D000":
            return True
        msg = str(cursor)
        if 'database "' in msg and "does not exist" in msg:
            return True
        cursor = cursor.__cause__ or cursor.__context__
    return False


def _run_migrations(log: logging.Logger) -> None:
    """Run ``alembic upgrade head`` against ``POSTGRES_URI``.

    Alembic serializes concurrent workers via its ``alembic_version``
    table, so no extra application-level locking is needed. Failures are
    logged and re-raised so the app fails fast.
    """
    from pathlib import Path

    # Lazy imports — alembic pulls in a fair amount of code.
    from alembic import command
    from alembic.config import Config
    from alembic.runtime.migration import MigrationContext
    from alembic.script import ScriptDirectory
    from sqlalchemy import create_engine

    # Mirror the discovery path used by scripts/db/init_postgres.py so
    # both entry points resolve the same alembic.ini regardless of cwd.
    alembic_ini = Path(__file__).resolve().parents[2] / "alembic.ini"
    if not alembic_ini.exists():
        raise RuntimeError(f"alembic.ini not found at {alembic_ini}")

    cfg = Config(str(alembic_ini))
    cfg.set_main_option("script_location", str(alembic_ini.parent / "alembic"))
    # We migrate in-process, after setup_logging() has configured the root
    # logger. env.py honours this by skipping fileConfig, which would
    # otherwise replace root's handlers and level for the rest of the process.
    cfg.attributes["configure_logger"] = False

    # Cheap pre-check: if we're already at head, say so explicitly.
    try:
        script = ScriptDirectory.from_config(cfg)
        head_rev = script.get_current_head()
        url = cfg.get_main_option("sqlalchemy.url")
        # env.py populates sqlalchemy.url from settings.POSTGRES_URI when
        # it's imported, but our Config instance hasn't loaded env.py
        # yet. Fall back to reading settings directly for the precheck.
        if not url:
            from application.core.settings import settings as _settings

            url = _settings.POSTGRES_URI
        current_rev: Optional[str] = None
        if url:
            precheck_engine = create_engine(url, pool_pre_ping=False)
            try:
                with precheck_engine.connect() as conn:
                    ctx = MigrationContext.configure(conn)
                    current_rev = ctx.get_current_revision()
            finally:
                precheck_engine.dispose()
        if current_rev is not None and current_rev == head_rev:
            log.info(
                "ensure_database_ready: migrations already at head (%s); "
                "nothing to do.",
                head_rev,
            )
            return
        log.info(
            "ensure_database_ready: applying Alembic migrations "
            "(current=%s, target=%s)...",
            current_rev,
            head_rev,
        )
    except Exception as exc:  # noqa: BLE001 — precheck is best-effort
        # If the precheck itself fails we still want to try the upgrade;
        # alembic will give a more actionable error if something's off.
        log.info(
            "ensure_database_ready: revision precheck failed (%s); "
            "proceeding with upgrade anyway.",
            exc,
        )

    try:
        command.upgrade(cfg, "head")
    except Exception as exc:  # noqa: BLE001 — surface everything
        log.error(
            "ensure_database_ready: alembic upgrade failed: %s. "
            "Check migration logs and DB connectivity; the app will not "
            "boot until this is resolved (or AUTO_MIGRATE is disabled).",
            exc,
        )
        raise
    log.info("ensure_database_ready: migrations applied.")
