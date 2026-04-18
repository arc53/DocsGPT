#!/usr/bin/env bash
# Reset the DocsGPT e2e DB by cloning it from the baked template.
#
# Called by scripts/e2e/up.sh at the start of each e2e run.
# Fast path: a single psql session does terminate + drop + clone.

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

log() {
  printf '[reset_db] %s\n' "$*" >&2
}

if [[ ! -x "${PSQL}" ]]; then
  log "psql not found at ${PSQL} — is DBngin Postgres 16.2 installed?"
  exit 1
fi

if ! "${PG_ISREADY}" -h "${PG_HOST}" -p "${PG_PORT}" -q; then
  log "Postgres is not accepting connections at ${PG_HOST}:${PG_PORT}."
  exit 1
fi

# Verify the template exists before attempting to clone from it.
template_exists="$(
  "${PSQL}" -h "${PG_HOST}" -p "${PG_PORT}" -U "${PG_SUPERUSER}" -d postgres \
    -tAX -c "SELECT 1 FROM pg_database WHERE datname = '${TEMPLATE_DB}';"
)"

if [[ "${template_exists}" != "1" ]]; then
  log "Template DB '${TEMPLATE_DB}' does not exist."
  log "Run scripts/e2e/bake_template.sh once before the first e2e run."
  exit 1
fi

"${PSQL}" -h "${PG_HOST}" -p "${PG_PORT}" -U "${PG_SUPERUSER}" -d postgres \
  -v ON_ERROR_STOP=1 -X -q <<SQL
SELECT pg_terminate_backend(pid)
  FROM pg_stat_activity
 WHERE datname = '${E2E_DB}'
   AND pid <> pg_backend_pid();

DROP DATABASE IF EXISTS ${E2E_DB};
CREATE DATABASE ${E2E_DB} TEMPLATE ${TEMPLATE_DB} OWNER ${OWNER_ROLE};
SQL

exit 0
