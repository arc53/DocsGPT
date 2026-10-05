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
#   HOME, XDG_CONFIG_HOME, XDG_CACHE_HOME, PYTHONUSERBASE -- a writable home
#     under /tmp (SANDBOX_KERNEL_HOME), because the root filesystem is read-only
#     and LibreOffice, Chromium, fontconfig, npm and `pip install --user` all
#     write under HOME. Its .local/bin is appended to PATH for pip-installed
#     commands.
#   Every NAME=value line of sandbox.env next to this script -- the image
#     environment from docsgpt/sandbox/manifest.py (generated; do not edit it).
#
# The image's smoke test runs the same way:
#   docker run --rm --read-only --tmpfs /tmp IMAGE \
#     /opt/docsgpt/kernel-env.sh python /opt/docsgpt/smoke_test.py
set -eu

KERNEL_HOME="${SANDBOX_KERNEL_HOME:-/tmp/home}"
ENV_FILE="$(dirname "$0")/sandbox.env"

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
