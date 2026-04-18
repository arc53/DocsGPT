#!/usr/bin/env bash
# scripts/e2e/up.sh
#
# Boot the DocsGPT end-to-end test stack on this machine, natively.
# See e2e-plan.md (Phase 0 / P0-A) for the contract.
#
# Happy path:
#   1. Preflight shared services (Postgres, Redis). Fail loud if down.
#   2. Reset state: Postgres template clone, Redis FLUSHDB 11/12/13, wipe .e2e-tmp.
#   3. Export env.
#   4. Start mock LLM (7899) → Flask (7099) → Celery → Vite (5179), each in
#      background, each with its own pidfile + log + readiness probe.
#   5. Exit 0, leaving services running. Playwright (or the user) invokes
#      down.sh separately when done.
#
# On error before handoff: tear everything down, non-zero exit.
# We explicitly DO NOT tear down on the happy-path exit — that would defeat
# the purpose of "up".

set -euo pipefail

# -----------------------------------------------------------------------------
# Paths
# -----------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

PG_BIN="/Users/Shared/DBngin/postgresql/16.2/bin"
DBNGIN_REDIS_BIN="/Users/Shared/DBngin/redis/7.0.0/bin"

# Resolve redis-cli — PATH first, then DBngin's bundled copy.
if command -v redis-cli >/dev/null 2>&1; then
    REDIS_CLI="$(command -v redis-cli)"
elif [[ -x "$DBNGIN_REDIS_BIN/redis-cli" ]]; then
    REDIS_CLI="$DBNGIN_REDIS_BIN/redis-cli"
else
    REDIS_CLI=""
fi
PIDDIR="/tmp/docsgpt-e2e"
E2E_TMP="$REPO_ROOT/.e2e-tmp"
LOGDIR="$E2E_TMP/logs"
BOOT_LOG="$LOGDIR/up.log"
SVC_LOGDIR="$PIDDIR"   # per-service logs live with the pidfiles per the brief

MOCK_LLM_PORT=7899
FLASK_PORT=7099
VITE_PORT=5179

# -----------------------------------------------------------------------------
# Bookkeeping — track which services we successfully started so we can tear
# them down if something later fails.
# -----------------------------------------------------------------------------
HANDOFF_OK=0
STARTED_SERVICES=()

log() {
    local msg="[up.sh] $*"
    # Goes to stderr so stdout stays clean; also mirrored to the boot log.
    echo "$msg" >&2
    if [[ -n "${BOOT_LOG:-}" ]] && [[ -d "$(dirname "$BOOT_LOG")" ]]; then
        echo "$msg" >> "$BOOT_LOG"
    fi
}

die() {
    log "ERROR: $*"
    exit 1
}

# Trap: if we exit before handoff (failure or Ctrl-C), clean up. The happy
# path sets HANDOFF_OK=1 just before `exit 0`, so the trap becomes a no-op.
cleanup_on_failure() {
    local rc=$?
    if [[ "$HANDOFF_OK" -eq 1 ]]; then
        return 0
    fi
    log "aborting — tearing down any services that started (rc=$rc)"
    if [[ -x "$SCRIPT_DIR/down.sh" ]]; then
        "$SCRIPT_DIR/down.sh" || true
    fi
}
trap cleanup_on_failure EXIT INT TERM

# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------

# Wait for a shell predicate to succeed. Args: <label> <timeout-seconds> <cmd...>
wait_for() {
    local label="$1"
    local timeout="$2"
    shift 2
    local elapsed=0
    while (( elapsed < timeout )); do
        if "$@" >/dev/null 2>&1; then
            log "  -> $label ready after ${elapsed}s"
            return 0
        fi
        sleep 1
        elapsed=$(( elapsed + 1 ))
    done
    return 1
}

# Wait for a substring to appear in a log file.
wait_for_log() {
    local label="$1"
    local timeout="$2"
    local logfile="$3"
    local needle="$4"
    local elapsed=0
    while (( elapsed < timeout )); do
        if [[ -f "$logfile" ]] && grep -qF -- "$needle" "$logfile"; then
            log "  -> $label saw '$needle' after ${elapsed}s"
            return 0
        fi
        sleep 1
        elapsed=$(( elapsed + 1 ))
    done
    return 1
}

# Dump last 50 lines of a log file to stderr (for boot-failure diagnostics).
dump_tail() {
    local label="$1"
    local logfile="$2"
    echo "---- last 50 lines of $label ($logfile) ----" >&2
    if [[ -f "$logfile" ]]; then
        tail -n 50 "$logfile" >&2 || true
    else
        echo "(log file does not exist)" >&2
    fi
    echo "---- end $label ----" >&2
}

# Boot-failure handler: dump the log, then let the trap tear everything down.
boot_fail() {
    local svc="$1"
    local logfile="$2"
    local reason="$3"
    log "boot failure: $svc — $reason"
    dump_tail "$svc" "$logfile"
    exit 1
}

# -----------------------------------------------------------------------------
# 1. Preflight
# -----------------------------------------------------------------------------
log "preflight: checking shared native services"

if [[ ! -x "$PG_BIN/pg_isready" ]]; then
    die "pg_isready not found at $PG_BIN/pg_isready — is DBngin Postgres 16.2 installed?"
fi

if ! "$PG_BIN/pg_isready" -h 127.0.0.1 -p 5432 -U docsgpt -d postgres >/dev/null 2>&1; then
    die "Postgres not reachable at 127.0.0.1:5432 as user 'docsgpt'. Start DBngin Postgres 16.2. (CLAUDE.md: do not kill/start this process from scripts.)"
fi
log "  -> postgres OK"

if [[ -z "$REDIS_CLI" ]]; then
    die "redis-cli not found on PATH nor at $DBNGIN_REDIS_BIN/redis-cli — install redis or adjust DBNGIN_REDIS_BIN"
fi

if ! "$REDIS_CLI" -h 127.0.0.1 -p 6379 PING 2>/dev/null | grep -q '^PONG$'; then
    die "Redis not reachable at 127.0.0.1:6379. Start the native redis-server. (CLAUDE.md: do not kill/start this process from scripts.)"
fi
log "  -> redis OK"

# -----------------------------------------------------------------------------
# 2. Reset state
# -----------------------------------------------------------------------------
log "resetting state"

# Wipe & recreate .e2e-tmp first so BOOT_LOG has a home.
rm -rf "$E2E_TMP"
mkdir -p "$E2E_TMP/inputs" "$E2E_TMP/indexes" "$LOGDIR"
: > "$BOOT_LOG"
log "  -> .e2e-tmp wiped; logs at $LOGDIR"

mkdir -p "$PIDDIR"
# Leave existing per-service logs alone until we overwrite them at launch time;
# that way a prior failure log isn't immediately erased if someone re-runs up.

# Postgres reset — delegated to reset_db.sh (owned by track P0-B).
RESET_DB_SCRIPT="$SCRIPT_DIR/reset_db.sh"
if [[ ! -x "$RESET_DB_SCRIPT" ]]; then
    die "reset_db.sh missing or not executable at $RESET_DB_SCRIPT — has track P0-B landed?"
fi
log "  -> invoking reset_db.sh"
if ! "$RESET_DB_SCRIPT" >> "$BOOT_LOG" 2>&1; then
    die "reset_db.sh failed — see $BOOT_LOG"
fi

# Redis reset — three dedicated DB indices.
for db in 11 12 13; do
    if ! "$REDIS_CLI" -h 127.0.0.1 -p 6379 -n "$db" FLUSHDB >/dev/null 2>&1; then
        die "redis-cli FLUSHDB failed on db $db"
    fi
done
log "  -> redis dbs 11/12/13 flushed"

# -----------------------------------------------------------------------------
# 3. Load env
# -----------------------------------------------------------------------------
log "sourcing env.sh"
# shellcheck source=./env.sh
source "$SCRIPT_DIR/env.sh"

# -----------------------------------------------------------------------------
# 4. Start services
# -----------------------------------------------------------------------------

# Pick Flask / python binaries from the repo venv when present.
if [[ -x "$REPO_ROOT/.venv/bin/flask" ]]; then
    FLASK_BIN="$REPO_ROOT/.venv/bin/flask"
else
    FLASK_BIN="$(command -v flask || true)"
fi
if [[ -z "$FLASK_BIN" ]]; then
    die "flask binary not found (.venv/bin/flask missing and no 'flask' on PATH)"
fi

if [[ -x "$REPO_ROOT/.venv/bin/python" ]]; then
    PY_BIN="$REPO_ROOT/.venv/bin/python"
else
    PY_BIN="$(command -v python3 || command -v python || true)"
fi
if [[ -z "$PY_BIN" ]]; then
    die "python binary not found (.venv/bin/python missing and no 'python3' on PATH)"
fi

log "using flask=$FLASK_BIN python=$PY_BIN"

# ---- 4a. Mock LLM ------------------------------------------------------------
MOCK_LLM_LOG="$SVC_LOGDIR/mock-llm.log"
MOCK_LLM_PID="$PIDDIR/mock-llm.pid"
log "starting mock LLM on 127.0.0.1:$MOCK_LLM_PORT"
(
    cd "$REPO_ROOT"
    # Port can be read from env by the script; we also export it for clarity.
    MOCK_LLM_PORT="$MOCK_LLM_PORT" PYTHONUNBUFFERED=1 nohup "$PY_BIN" scripts/e2e/mock_llm.py \
        >"$MOCK_LLM_LOG" 2>&1 &
    echo $! > "$MOCK_LLM_PID"
)
STARTED_SERVICES+=("mock-llm")

if ! wait_for "mock-llm /healthz" 10 \
        curl -sf "http://127.0.0.1:${MOCK_LLM_PORT}/healthz"; then
    boot_fail "mock-llm" "$MOCK_LLM_LOG" "healthz did not respond within 10s"
fi

# ---- 4b. Flask ---------------------------------------------------------------
FLASK_LOG="$SVC_LOGDIR/flask.log"
FLASK_PID="$PIDDIR/flask.pid"
log "starting Flask on 127.0.0.1:$FLASK_PORT"
(
    cd "$E2E_TMP"
    PYTHONUNBUFFERED=1 nohup "$FLASK_BIN" --app ../application/app.py run \
        --host 127.0.0.1 --port "$FLASK_PORT" \
        >"$FLASK_LOG" 2>&1 &
    echo $! > "$FLASK_PID"
)
STARTED_SERVICES+=("flask")

if ! wait_for "flask /api/config" 30 \
        curl -sf "http://127.0.0.1:${FLASK_PORT}/api/config"; then
    boot_fail "flask" "$FLASK_LOG" "/api/config did not respond within 30s"
fi

# ---- 4c. Celery --------------------------------------------------------------
CELERY_LOG="$SVC_LOGDIR/celery.log"
CELERY_PID="$PIDDIR/celery.pid"
log "starting Celery worker (solo pool)"
(
    cd "$E2E_TMP"
    PYTHONPATH="$REPO_ROOT${PYTHONPATH:+:$PYTHONPATH}" \
    PYTHONUNBUFFERED=1 \
    nohup "$PY_BIN" -m celery -A application.app.celery worker \
        -l INFO --pool=solo \
        --without-gossip --without-mingle --without-heartbeat \
        >"$CELERY_LOG" 2>&1 &
    echo $! > "$CELERY_PID"
)
STARTED_SERVICES+=("celery")

# Celery's "ready" banner contains both "celery@<host>" and "ready.". Wait for
# both in sequence so we know the worker actually finished bootstrapping.
if ! wait_for_log "celery 'celery@'" 30 "$CELERY_LOG" "celery@"; then
    boot_fail "celery" "$CELERY_LOG" "never emitted 'celery@' banner within 30s"
fi

# Ready check via `celery inspect ping`. We can't grep the log for 'ready'
# because application/core/logging_config.py calls dictConfig with the default
# disable_existing_loggers=True, which silences celery.worker's ready banner.
# `inspect ping` queries the worker over the broker — it's the canonical
# responsiveness check and doesn't depend on log output.
CELERY_INSPECT_TIMEOUT=45
elapsed=0
ping_ok=0
while (( elapsed < CELERY_INSPECT_TIMEOUT )); do
    if ( cd "$E2E_TMP" && \
         PYTHONPATH="$REPO_ROOT${PYTHONPATH:+:$PYTHONPATH}" \
         PYTHONUNBUFFERED=1 \
         "$PY_BIN" -m celery -A application.app.celery inspect ping \
             --timeout 2 >/dev/null 2>&1 ); then
        ping_ok=1
        log "  -> celery inspect ping OK after ${elapsed}s"
        break
    fi
    sleep 1
    elapsed=$(( elapsed + 1 ))
done
if (( ping_ok == 0 )); then
    boot_fail "celery" "$CELERY_LOG" "worker did not respond to 'inspect ping' within ${CELERY_INSPECT_TIMEOUT}s"
fi

# ---- 4d. Vite dev server -----------------------------------------------------
VITE_LOG="$SVC_LOGDIR/vite.log"
VITE_PID="$PIDDIR/vite.pid"
log "starting Vite dev server on 127.0.0.1:$VITE_PORT"
(
    cd "$REPO_ROOT/frontend"
    VITE_API_HOST="http://127.0.0.1:${FLASK_PORT}" nohup npm run dev -- \
        --host 127.0.0.1 --port "$VITE_PORT" --strictPort \
        >"$VITE_LOG" 2>&1 &
    echo $! > "$VITE_PID"
)
STARTED_SERVICES+=("vite")

# Prefer nc; fall back to lsof. Either succeeding means the port is LISTEN.
vite_ready() {
    if command -v nc >/dev/null 2>&1; then
        nc -z 127.0.0.1 "$VITE_PORT" >/dev/null 2>&1 && return 0
    fi
    if command -v lsof >/dev/null 2>&1; then
        [[ -n "$(lsof -nP -iTCP:"$VITE_PORT" -sTCP:LISTEN -t 2>/dev/null)" ]] && return 0
    fi
    return 1
}

if ! wait_for "vite LISTEN on $VITE_PORT" 20 vite_ready; then
    boot_fail "vite" "$VITE_LOG" "port $VITE_PORT never entered LISTEN within 20s"
fi

# -----------------------------------------------------------------------------
# 5. Handoff
# -----------------------------------------------------------------------------
log "all services up:"
log "  mock-llm  pid=$(cat "$MOCK_LLM_PID") log=$MOCK_LLM_LOG"
log "  flask     pid=$(cat "$FLASK_PID")    log=$FLASK_LOG"
log "  celery    pid=$(cat "$CELERY_PID")   log=$CELERY_LOG"
log "  vite      pid=$(cat "$VITE_PID")     log=$VITE_LOG"
log "handoff complete — exiting 0, services remain running. Run scripts/e2e/down.sh to stop."

HANDOFF_OK=1
exit 0
