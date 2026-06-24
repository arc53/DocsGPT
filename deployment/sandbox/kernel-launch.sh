#!/bin/sh
# Env-scrubbing launcher for the docsgpt-sandbox ipykernel.
#
# The gateway process inherits the operator's full environment, which can carry
# secrets (*_API_KEY, *_TOKEN, POSTGRES_URI, the gateway auth token, ...). Stock
# kernels inherit that env verbatim, so LLM-authored code could read it via
# os.environ. This wrapper re-execs ipykernel under a MINIMAL allowlisted env so
# NO secret reaches kernel code, regardless of how the gateway was launched.
#
# Only what ipykernel needs is kept: PATH (find python), HOME (~/.ipython etc),
# LANG (encoding), and the Jupyter runtime/data dirs (writable tmpfs paths). The
# {connection_file} the gateway passes is forwarded via "$@" so loopback ZMQ
# reachability is preserved -- do NOT drop or rewrite those args.
exec env -i \
    PATH="${PATH}" \
    HOME="${HOME}" \
    LANG="${LANG}" \
    JUPYTER_RUNTIME_DIR="${JUPYTER_RUNTIME_DIR}" \
    JUPYTER_DATA_DIR="${JUPYTER_DATA_DIR}" \
    python -m ipykernel_launcher "$@"
