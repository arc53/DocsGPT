#!/bin/sh
# Entrypoint for the docsgpt-sandbox Jupyter Kernel Gateway.
#
# The gateway and every session kernel share this one container, so LLM-authored
# kernel code can reach the gateway's control API over loopback
# (http://localhost:8888). WITHOUT authentication that means kernel code could
# enumerate/attach/kill sibling sessions' kernels and spawn kernels without bound
# (bypassing the app-side session cap). We therefore REQUIRE an auth token and
# fail closed if it is missing -- an unauthenticated gateway must never start.
#
# The token is shared with the app via SANDBOX_GATEWAY_AUTH_TOKEN (the app sends
# it as `Authorization: token <...>`). kernel-launch.sh re-execs ipykernel under a
# scrubbed `env -i` allowlist that excludes the token, so it is NOT in kernel code's
# os.environ. NOTE: this is not a hard secret boundary -- the gateway and kernels
# share one container and uid, so kernel code can still read the gateway's env via
# /proc/<gateway_pid>/environ. The token limits the blast radius (an outside caller
# cannot drive the gateway), but the Jupyter runner is a single trust domain: for
# real isolation against untrusted code use the Daytona backend or run under gVisor
# (see deployment/sandbox/README.md).
set -eu

TOKEN="${SANDBOX_GATEWAY_AUTH_TOKEN:-}"
if [ -z "$TOKEN" ]; then
    echo "docsgpt-sandbox: refusing to start an unauthenticated gateway." >&2
    echo "Set SANDBOX_GATEWAY_AUTH_TOKEN (same value on the app and this container)." >&2
    exit 1
fi

# ip=0.0.0.0 so the backend/worker can reach it over the internal sandbox network.
# auth_token gates every HTTP + WebSocket request, including loopback ones from
# kernel code. limit_rate=False raises the iopub data-rate cap so large get_file
# base64 payloads are not truncated (the get_file integrity check still guards
# truncation if this is ever off).
exec jupyter kernelgateway \
    --KernelGatewayApp.ip=0.0.0.0 \
    --KernelGatewayApp.port=8888 \
    --KernelGatewayApp.auth_token="$TOKEN" \
    --ZMQChannelsWebsocketConnection.limit_rate=False
