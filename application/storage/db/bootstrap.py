"""Self-bootstrapping database setup for the DocsGPT user-data Postgres DB.

On app startup the Flask factory (and Celery worker init) can call
:func:`ensure_database_ready` to:

1. Create the target database if it's missing (dev-friendly; requires the
   configured role to have ``CREATEDB`` privilege).
2. Apply every pending Alembic migration up to ``head``.

Both steps are gated by settings that default ON for dev convenience and
can be turned off in prod (``AUTO_CREATE_DB`` / ``AUTO_MIGRATE``) where
schema is managed out-of-band by a deploy pipeline.

All heavy imports (alembic, psycopg, sqlalchemy.exc sub-symbols) are
deferred to inside the function so merely importing this module has no
side effects and is cheap for test collection.
"""

from __future__ import annotations

import logging
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
