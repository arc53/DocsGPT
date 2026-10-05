#!/bin/sh
# Env-scrubbing launcher for the docsgpt-sandbox ipykernel.
#
# kernel.json starts every kernel through this script. It re-execs ipykernel
# through kernel-env.sh, which drops the gateway's environment (and any secret in
# it) for a minimal allowlist plus a writable HOME; see that script. The
# {connection_file} the gateway passes is forwarded via "$@" so loopback ZMQ
# reachability is preserved -- do NOT drop or rewrite those args.
exec sh "$(dirname "$0")/kernel-env.sh" python -m ipykernel_launcher "$@"
