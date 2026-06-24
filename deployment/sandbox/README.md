# docsgpt-sandbox runner

Always-on Jupyter Kernel Gateway that executes sandboxed LLM code. The DocsGPT
backend/worker is the **client** and connects over HTTP + WebSocket via
`SANDBOX_GATEWAY_URL`. Each session is an **in-process kernel** (child process),
never a child container; the Docker socket is **not** mounted.

## Run standalone for dev

Build and run the runner on its own, then point the app at it:

```bash
docker build -t docsgpt-sandbox deployment/sandbox
docker run --rm -p 8888:8888 docsgpt-sandbox
# in the app's .env:  SANDBOX_GATEWAY_URL=http://localhost:8888
```

Without Docker (matches the test harness) you can run the gateway directly from
a venv that has `jupyter-kernel-gateway` installed:

```bash
jupyter kernelgateway --KernelGatewayApp.ip=0.0.0.0 --KernelGatewayApp.port=8888 \
  --ZMQChannelsWebsocketConnection.limit_rate=False
```

`--ZMQChannelsWebsocketConnection.limit_rate=False` raises the iopub data-rate
limit so large `get_file` base64 payloads aren't silently truncated. (On older
gateways the trait may live elsewhere; the client's `get_file` integrity check
catches any truncation regardless.)

## Exposing the port requires auth

The image does **not** set `--KernelGatewayApp.allow_origin=*`. If you publish
port 8888 (e.g. `docker run -p 8888:8888`), set `SANDBOX_GATEWAY_AUTH_TOKEN`
and launch the gateway with a matching `--KernelGatewayApp.auth_token` so the
runner is not an open arbitrary-code-execution endpoint. In compose the runner
stays on the internal-only network with no published port, so no token is
required there.

## In docker-compose

The `docsgpt-sandbox` service is defined in `deployment/docker-compose.yaml` on
an internal-only network. The backend and worker reach it at
`http://docsgpt-sandbox:8888`.

## Hardening (separate slice — not in this image)

Egress/SSRF blocks (drop RFC1918, link-local, `169.254.169.254`), the gVisor
`runsc` runtime, seccomp, read-only root FS, and cgroup CPU/mem/PID caps wired
from `SANDBOX_MEMORY` / `SANDBOX_CPUS` land in the hardening slice.
