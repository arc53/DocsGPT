#!/usr/bin/env bash
# One-time bootstrap for the DocsGPT e2e Postgres template DB.
#
# Creates two databases on the native DBngin Postgres instance:
#   * docsgpt_e2e_template  — schema-only (alembic head), marked as a PG template
#   * docsgpt_e2e           — the live DB the first `up.sh` run connects to
#
# Idempotent. Safe to re-run after schema changes to refresh the template.

set -euo pipefail

PG_BIN="/Users/Shared/DBngin/postgresql/16.2/bin"
PSQL="${PG_BIN}/psql"
PG_ISREADY="${PG_BIN}/pg_isready"

PG_HOST="127.0.0.1"
PG_PORT="5432"
PG_SUPERUSER="postgres"

TEMPLATE_DB="docsgpt_e2e_template"
E2E_DB="docsgpt_e2e"
OWNER_ROLE="docsgpt"
OWNER_PASSWORD="docsgpt"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

log() {
  printf '[bake_template] %s\n' "$*" >&2
}

if [[ ! -x "${PSQL}" ]]; then
  log "psql not found at ${PSQL} — is DBngin Postgres 16.2 installed?"
  exit 1
fi

log "Checking Postgres is up at ${PG_HOST}:${PG_PORT}..."
if ! "${PG_ISREADY}" -h "${PG_HOST}" -p "${PG_PORT}" -q; then
  log "Postgres is not accepting connections at ${PG_HOST}:${PG_PORT}."
  log "Start DBngin's Postgres 16.2 instance and try again."
  exit 1
fi

log "Dropping and recreating ${TEMPLATE_DB} as superuser ${PG_SUPERUSER}..."
"${PSQL}" -h "${PG_HOST}" -p "${PG_PORT}" -U "${PG_SUPERUSER}" -d postgres \
  -v ON_ERROR_STOP=1 -X -q <<SQL
-- Clear the template flag first so DROP DATABASE is allowed.
UPDATE pg_database SET datistemplate = FALSE WHERE datname = '${TEMPLATE_DB}';
UPDATE pg_database SET datallowconn = TRUE  WHERE datname = '${TEMPLATE_DB}';

-- Evict any lingering backends on the template DB.
SELECT pg_terminate_backend(pid)
  FROM pg_stat_activity
 WHERE datname = '${TEMPLATE_DB}'
   AND pid <> pg_backend_pid();

DROP DATABASE IF EXISTS ${TEMPLATE_DB};
CREATE DATABASE ${TEMPLATE_DB} OWNER ${OWNER_ROLE};
SQL

log "Applying Alembic schema to ${TEMPLATE_DB}..."

if [[ -x "${REPO_ROOT}/.venv/bin/python" ]]; then
  PYTHON="${REPO_ROOT}/.venv/bin/python"
else
  PYTHON="python3"
fi

(
  cd "${REPO_ROOT}"
  POSTGRES_URI="postgresql://${OWNER_ROLE}:${OWNER_PASSWORD}@${PG_HOST}:${PG_PORT}/${TEMPLATE_DB}" \
    "${PYTHON}" scripts/db/init_postgres.py
)

log "Marking ${TEMPLATE_DB} as a Postgres template (datistemplate=TRUE, datallowconn=FALSE)..."
"${PSQL}" -h "${PG_HOST}" -p "${PG_PORT}" -U "${PG_SUPERUSER}" -d postgres \
  -v ON_ERROR_STOP=1 -X -q <<SQL
UPDATE pg_database SET datistemplate = TRUE  WHERE datname = '${TEMPLATE_DB}';
UPDATE pg_database SET datallowconn = FALSE WHERE datname = '${TEMPLATE_DB}';
SQL

log "Cloning ${E2E_DB} from ${TEMPLATE_DB}..."
"${PSQL}" -h "${PG_HOST}" -p "${PG_PORT}" -U "${PG_SUPERUSER}" -d postgres \
  -v ON_ERROR_STOP=1 -X -q <<SQL
SELECT pg_terminate_backend(pid)
  FROM pg_stat_activity
 WHERE datname = '${E2E_DB}'
   AND pid <> pg_backend_pid();

DROP DATABASE IF EXISTS ${E2E_DB};
CREATE DATABASE ${E2E_DB} TEMPLATE ${TEMPLATE_DB} OWNER ${OWNER_ROLE};
SQL

log "Done. Template ${TEMPLATE_DB} is baked; ${E2E_DB} is ready for the first e2e run."
exit 0
