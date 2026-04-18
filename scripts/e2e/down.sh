#!/usr/bin/env bash
# scripts/e2e/down.sh
#
# Tear down the DocsGPT end-to-end test stack started by up.sh.
# Reads pidfiles from /tmp/docsgpt-e2e/*.pid, sends SIGTERM, waits up to 3s,
# escalates to SIGKILL if still alive, removes each pidfile.
#
# Constraints:
#   - Idempotent: exits 0 even when no pidfiles exist.
#   - NEVER uses pkill/killall (CLAUDE.md: don't risk killing native
#     Postgres/Redis/Mongo processes).
#   - NEVER touches shared DB/Redis services.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

PIDDIR="/tmp/docsgpt-e2e"

log() {
    echo "[down.sh] $*" >&2
}

# Stop a single service given its pidfile. Best-effort; never fatal.
stop_one() {
    local pidfile="$1"
    local svc
    svc="$(basename "$pidfile" .pid)"

    if [[ ! -s "$pidfile" ]]; then
        log "$svc: pidfile empty or missing — removing"
        rm -f "$pidfile"
        return 0
    fi

    local pid
    pid="$(cat "$pidfile" 2>/dev/null || true)"

    # Guard against garbage in the pidfile (non-numeric or empty).
    if ! [[ "$pid" =~ ^[0-9]+$ ]]; then
        log "$svc: pidfile contents not numeric ('$pid') — removing"
        rm -f "$pidfile"
        return 0
    fi

    if ! kill -0 "$pid" 2>/dev/null; then
        log "$svc: pid $pid not running — removing pidfile"
        rm -f "$pidfile"
        return 0
    fi

    log "$svc: sending SIGTERM to pid $pid"
    kill "$pid" 2>/dev/null || true

    # Poll up to 3 seconds for graceful exit.
    local waited=0
    while (( waited < 3 )); do
        if ! kill -0 "$pid" 2>/dev/null; then
            break
        fi
        sleep 1
        waited=$(( waited + 1 ))
    done

    if kill -0 "$pid" 2>/dev/null; then
        log "$svc: pid $pid still alive after 3s — SIGKILL"
        kill -9 "$pid" 2>/dev/null || true
    else
        log "$svc: pid $pid exited gracefully"
    fi

    rm -f "$pidfile"
}

if [[ ! -d "$PIDDIR" ]]; then
    log "no pid directory at $PIDDIR — nothing to stop"
    exit 0
fi

shopt -s nullglob
pidfiles=( "$PIDDIR"/*.pid )
shopt -u nullglob

if (( ${#pidfiles[@]} == 0 )); then
    log "no pidfiles in $PIDDIR — nothing to stop"
    exit 0
fi

for pidfile in "${pidfiles[@]}"; do
    stop_one "$pidfile"
done

log "teardown complete"
exit 0
