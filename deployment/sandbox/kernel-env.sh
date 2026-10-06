#!/bin/sh
# Run a command under the sandbox kernel's scrubbed environment.
#
# The gateway process inherits the operator's full environment, which can carry
# secrets (*_API_KEY, *_TOKEN, POSTGRES_URI, the gateway auth token, ...). Stock
# kernels inherit that env verbatim, so LLM-authored code could read it via
# os.environ. kernel-launch.sh runs ipykernel through this script, which execs
# the command under `env -i` with a MINIMAL allowlist, so NO secret reaches
# kernel code, regardless of how the gateway was launched.
#
# Kept: PATH (find python), LANG (encoding) and the Jupyter runtime/data dirs
# (writable tmpfs paths). Set here:
#   HOME, XDG_CONFIG_HOME, XDG_CACHE_HOME, PYTHONUSERBASE -- a writable home,
#     because the root filesystem is read-only and LibreOffice, Chromium,
#     fontconfig, npm and `pip install --user` (packages and pip's cache) all
#     write under HOME. Its .local/bin is appended to PATH for pip-installed
#     commands.
#   Every NAME=value line of sandbox.env next to this script -- the image
#     environment from docsgpt/sandbox/manifest.py (generated; do not edit it).
#
# Where HOME goes, first match wins:
#   1. SANDBOX_KERNEL_HOME, when set.
#   2. $SANDBOX_HOME_MOUNT/home (default /sandbox-home/home) when that mount is
#      there, writable and not noexec. Compose and Kubernetes mount it as a
#      tmpfs that allows exec (still nosuid,nodev), so a compiled package
#      pip-installed at runtime can map its .so files. /tmp stays noexec.
#   3. $SANDBOX_TMP_HOME (default /tmp/home), with a one-line note on stderr:
#      the image was started without the mount (an older compose file, a plain
#      `docker run`). Everything works except compiled packages installed at
#      runtime, which fail with "failed to map segment from shared object".
# SANDBOX_PROC_MOUNTS (default /proc/mounts) is where the mount options are read.
#
# The image's smoke test runs the same way:
#   docker run --rm --read-only --tmpfs /tmp \
#     --tmpfs /sandbox-home:rw,exec,nosuid,nodev,size=1g,uid=10001,gid=10001,mode=0700 IMAGE \
#     /opt/docsgpt/kernel-env.sh python /opt/docsgpt/smoke_test.py
set -eu

HOME_MOUNT="${SANDBOX_HOME_MOUNT:-/sandbox-home}"
TMP_HOME="${SANDBOX_TMP_HOME:-/tmp/home}"
PROC_MOUNTS="${SANDBOX_PROC_MOUNTS:-/proc/mounts}"
ENV_FILE="$(dirname "$0")/sandbox.env"

# True when $1 is a writable directory whose mount does not forbid exec.
exec_mount() {
    [ -d "$1" ] && [ -w "$1" ] || return 1
    [ -r "$PROC_MOUNTS" ] || return 0
    # Field 2 is the mount point, field 4 its options; the last entry for a path wins.
    options="$(awk -v dir="$1" '$2 == dir { opts = $4 } END { print opts }' "$PROC_MOUNTS")"
    case ",$options," in
        *,noexec,*) return 1 ;;
    esac
    return 0
}

if [ -n "${SANDBOX_KERNEL_HOME:-}" ]; then
    KERNEL_HOME="$SANDBOX_KERNEL_HOME"
elif exec_mount "$HOME_MOUNT"; then
    KERNEL_HOME="$HOME_MOUNT/home"
else
    KERNEL_HOME="$TMP_HOME"
    echo "kernel-env: no writable exec-enabled $HOME_MOUNT mount; HOME is $KERNEL_HOME, where compiled packages pip-installed at runtime fail to load if it is noexec (as /tmp is under compose)" >&2
fi

mkdir -p -m 0700 "$KERNEL_HOME"
mkdir -p "$KERNEL_HOME/.config" "$KERNEL_HOME/.cache" "$KERNEL_HOME/.local/bin"

KERNEL_PATH="${PATH}:${KERNEL_HOME}/.local/bin"

# Python adds the user site-packages dir to sys.path only if it exists when the
# interpreter starts. Create it now so a package pip-installed (--user) from a
# running kernel imports without a restart.
user_site="$(env -i PATH="$KERNEL_PATH" PYTHONUSERBASE="$KERNEL_HOME/.local" \
    python -c 'import site; print(site.getusersitepackages())' 2>/dev/null || true)"
nl='
'
case "$user_site" in
    *"$nl"*) ;;
    "$KERNEL_HOME"/*site-packages) mkdir -p "$user_site" ;;
esac

# Prepend the image env (one NAME=value per line) to the command, so `env`
# below sets it. Lines that are not assignments are skipped, never evaluated.
if [ -r "$ENV_FILE" ]; then
    while IFS= read -r line || [ -n "$line" ]; do
        case "$line" in
            '' | '#'*) ;;
            [A-Z_]*=*)
                case "${line%%=*}" in
                    *[!A-Z0-9_]*) echo "kernel-env: skipping malformed line in $ENV_FILE: $line" >&2 ;;
                    *) set -- "$line" "$@" ;;
                esac
                ;;
            *) echo "kernel-env: skipping malformed line in $ENV_FILE: $line" >&2 ;;
        esac
    done < "$ENV_FILE"
fi

exec env -i \
    PATH="$KERNEL_PATH" \
    HOME="$KERNEL_HOME" \
    XDG_CONFIG_HOME="$KERNEL_HOME/.config" \
    XDG_CACHE_HOME="$KERNEL_HOME/.cache" \
    PYTHONUSERBASE="$KERNEL_HOME/.local" \
    LANG="${LANG:-C.UTF-8}" \
    JUPYTER_RUNTIME_DIR="${JUPYTER_RUNTIME_DIR:-}" \
    JUPYTER_DATA_DIR="${JUPYTER_DATA_DIR:-}" \
    "$@"
