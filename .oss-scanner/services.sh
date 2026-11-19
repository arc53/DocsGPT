#!/usr/bin/env bash
# Start PostgreSQL and Redis inside the scanner image and prepare a database,
# so a DocsGPT instance can run there without a network. Run it as root or as
# the docsgpt user; it is safe to run twice.
set -euo pipefail

PGDATA=/home/docsgpt/pgdata
as_docsgpt() {
  if [ "$(id -u)" = 0 ]; then
    runuser -u docsgpt -- env HOME=/home/docsgpt "$@"
  else
    "$@"
  fi
}

if [ ! -s "$PGDATA/PG_VERSION" ]; then
  as_docsgpt initdb -D "$PGDATA" -U postgres --auth=trust --encoding=UTF8 --locale=C.UTF-8 >/dev/null
fi
if ! as_docsgpt pg_ctl -D "$PGDATA" status >/dev/null; then
  as_docsgpt pg_ctl -D "$PGDATA" -l "$PGDATA/server.log" \
    -o "-c listen_addresses=127.0.0.1 -c unix_socket_directories=/tmp" -w start >/dev/null
fi
as_docsgpt psql -h 127.0.0.1 -U postgres -d postgres -qtA <<'SQL'
DO $$ BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'docsgpt') THEN
    CREATE ROLE docsgpt LOGIN SUPERUSER PASSWORD 'docsgpt';
  END IF;
END $$;
SELECT 'CREATE DATABASE docsgpt OWNER docsgpt'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'docsgpt') \gexec
SQL

if ! redis-cli -h 127.0.0.1 ping >/dev/null 2>&1; then
  as_docsgpt redis-server --bind 127.0.0.1 --daemonize yes --dir /home/docsgpt --save "" >/dev/null
fi

if [ ! -e /src/.env ]; then
  as_docsgpt tee /src/.env >/dev/null <<ENV
POSTGRES_URI=postgresql://docsgpt:docsgpt@127.0.0.1:5432/docsgpt
CELERY_BROKER_URL=redis://127.0.0.1:6379/0
CELERY_RESULT_BACKEND=redis://127.0.0.1:6379/1
CACHE_REDIS_URL=redis://127.0.0.1:6379/2
INTERNAL_KEY=$(head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n')
ENV
fi

if ! (cd /src && as_docsgpt docsgpt migrate >/tmp/docsgpt-migrate.log 2>&1); then
  echo "docsgpt migrate failed; see /tmp/docsgpt-migrate.log" >&2
  exit 1
fi

echo "PostgreSQL on 127.0.0.1:5432 (database, role and password: docsgpt), Redis on 127.0.0.1:6379."
echo "Settings are in /src/.env. Next: .oss-scanner/as-docsgpt.sh docsgpt dev --mock-llm"
