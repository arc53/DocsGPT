# docsgpt-sandbox runner

Opt-in Jupyter Kernel Gateway that executes sandboxed LLM code. The DocsGPT
backend/worker is the **client** and connects over HTTP + WebSocket via
`SANDBOX_GATEWAY_URL`. Each session is an **in-process kernel** (child process),
never a child container; the Docker socket is **not** mounted.

## Enabling code execution (opt-in)

The runner is **opt-in**. Neither `code_executor` nor `artifact_generator` is a
default chat tool (both were removed from `DEFAULT_CHAT_TOOLS`), and the runner
is **not** part of the base compose stack — a plain `docker compose up` does
**not** start `docsgpt-sandbox`. Enable it by layering the sandbox overlay and
setting a shared gateway token:

```bash
export SANDBOX_GATEWAY_AUTH_TOKEN=$(openssl rand -hex 32)
docker compose \
  -f deployment/docker-compose.yaml \
  -f deployment/optional/docker-compose.optional.sandbox.yaml up
```

The token is **required** — the gateway fails closed if it is unset (see
*Gateway authentication* below). Add the egress-firewall overlay for SSRF
containment (see *Network egress / SSRF*):

```bash
docker compose \
  -f deployment/docker-compose.yaml \
  -f deployment/optional/docker-compose.optional.sandbox.yaml \
  -f deployment/optional/docker-compose.optional.sandbox-egress.yaml up
```

Then enable `code_executor` / `artifact_generator` **per-agent** in the agent
tool picker. Agents without them never call the runner, and the backend/worker
degrade gracefully when the runner is absent. The `-hub` and `-azure` compose
variants take the same sandbox overlay.

## Isolation model

Read this before pointing untrusted or multi-tenant workloads at the runner.

A single Jupyter runner is **one trust domain**. Every session is an in-process
kernel under **one shared uid (10001)** in **one container**; sessions are
isolated by **working directory only** — each session's code runs with its cwd
set to its own `/tmp/docsgpt-sandbox/<session_id>` directory. That is a
convenience boundary, not a security boundary between sessions.

What this slice does close:

- **Env-secret exfil is closed.** The custom kernelspec
  (`kernels/docsgpt-python/kernel.json` → `/opt/docsgpt/kernel-launch.sh`)
  re-execs ipykernel under a minimal allowlisted env (`env -i` keeping only
  `PATH`, `HOME`, `LANG`, `JUPYTER_RUNTIME_DIR`, `JUPYTER_DATA_DIR`). The image
  installs this spec under the **distinct name `docsgpt-python`** and the app
  selects it via `SANDBOX_KERNEL_NAME=docsgpt-python`; because the name is
  distinct, it is **never shadowed** by the stock ipykernel `python3` spec
  (kernelspec name resolution prefers `sys.prefix/share` over
  `/usr/local/share`, so reusing `python3` would silently fall back to the
  unscrubbed stock spec on a different python prefix). The stock `python3` spec
  is left untouched. So even though the gateway process inherits the operator's
  full environment, **no `*_API_KEY` / `*_TOKEN` / `POSTGRES_URI` / gateway auth
  token reaches kernel code** via `os.environ`, regardless of how the gateway is
  launched. Loopback ZMQ reachability is preserved because `{connection_file}`
  is forwarded untouched.
- **Per-session workspace perms.** The workspace root and each session dir are
  created `0700` (defense-in-depth). Under one shared uid this does **not** stop
  a sibling session from reading another's files — it only narrows exposure to
  other uids on the box.

Residual gaps (treat all sessions in one runner as mutually trusting):

- **Sibling-workspace reads.** All kernels run as the same uid, so one session's
  code can read another session's files (and `/tmp`) despite `0700`. Distinct
  uids / per-session VMs are required to close this.
- **In-memory / cross-kernel.** Kernels are child processes of one gateway under
  one uid; OS-level process isolation is the only boundary, and it is not a
  sandbox boundary against a determined escape. No gVisor in the base posture.
  (The gateway's HTTP/WebSocket control API is reachable from kernel code over
  loopback, but it is **authenticated** — see *Gateway authentication* — and the
  token is scrubbed from the kernel env, so kernel code cannot drive it to
  enumerate/kill sibling kernels or spawn kernels past the session cap.)
- **Egress.** Outbound is broad by design (so code can `pip install` / call
  public APIs). Private/link-local/metadata ranges are blocked **only** by the
  network layer — the k8s NetworkPolicy or a host/cloud firewall (see *Network
  egress / SSRF* below), never by the runner itself.

For real per-tenant isolation (cross-tenant or untrusted code), use the
**Daytona backend** (`SANDBOX_BACKEND=daytona`), which gives each session its
own VM. To harden the self-hosted Jupyter runner as a whole (host protection +
egress), layer the **gVisor `runsc` runtime**, the **NetworkPolicy**, and a
**host firewall** as documented below — those protect the host and constrain
egress; they do **not** create a boundary between sessions inside one runner.

## Run standalone for dev

Build and run the runner on its own, then point the app at it:

```bash
docker build -t docsgpt-sandbox deployment/sandbox
docker run --rm -p 8888:8888 -e SANDBOX_GATEWAY_AUTH_TOKEN=devtoken docsgpt-sandbox
# in the app's .env:  SANDBOX_GATEWAY_URL=http://localhost:8888
#                     SANDBOX_GATEWAY_AUTH_TOKEN=devtoken
```

The token is required — the image's entrypoint refuses to start without it (see
*Gateway authentication*). Without Docker (matches the test harness) you can run
the gateway directly from a venv that has `jupyter-kernel-gateway` installed; set
a matching `--KernelGatewayApp.auth_token`:

```bash
jupyter kernelgateway --KernelGatewayApp.ip=0.0.0.0 --KernelGatewayApp.port=8888 \
  --KernelGatewayApp.auth_token=devtoken \
  --ZMQChannelsWebsocketConnection.limit_rate=False
```

`--ZMQChannelsWebsocketConnection.limit_rate=False` raises the iopub data-rate
limit so large `get_file` base64 payloads aren't silently truncated. (On older
gateways the trait may live elsewhere; the client's `get_file` integrity check
catches any truncation regardless.)

A bare-venv gateway uses the **stock** `python3` kernelspec, which inherits the
gateway's full env (no secret scrubbing). The default `SANDBOX_KERNEL_NAME` is
`python3`, so plain venv dev gets no scrubbing — acceptable for single-trust
dev. The Docker image instead ships the env-scrubbing spec under the distinct
name `docsgpt-python` (see *Isolation model*) and the runner stack sets
`SANDBOX_KERNEL_NAME=docsgpt-python`. To get the scrubbing behavior in a venv,
copy `kernels/docsgpt-python/kernel.json` (pointing `argv` at a local copy of
`kernel-launch.sh`) into a Jupyter data dir on the kernelspec search path and
set `SANDBOX_KERNEL_NAME=docsgpt-python` before launching.

## Gateway authentication

The gateway **requires** an auth token and **fails closed** if it is unset — the
image's entrypoint (`gateway-launch.sh`) refuses to start an unauthenticated
gateway. This matters even on an internal-only network: the gateway and every
session kernel share one container, so kernel code can reach the gateway's
control API over **loopback** (`http://localhost:8888`). Without auth, that
control API would let kernel code enumerate/attach/kill sibling sessions'
kernels and spawn kernels without bound (bypassing the app-side session cap).

Set the same token on the runner and the app via `SANDBOX_GATEWAY_AUTH_TOKEN`
(the app sends it as `Authorization: token <...>`; the runner's gateway
validates it on every HTTP + WebSocket request). Kernel code cannot read it: the
kernelspec launcher scrubs it from the kernel env (see *Isolation model*), so it
is present for the gateway process only. The image also does **not** set
`--KernelGatewayApp.allow_origin=*`.

## In docker-compose

The `docsgpt-sandbox` service lives in the opt-in overlay
`deployment/optional/docker-compose.optional.sandbox.yaml` (layered on the base
stack; see *Enabling code execution (opt-in)*) on an internal-only network with
no published host port. The overlay puts the backend and worker on `sandbox-net`
to reach the runner at `http://docsgpt-sandbox:8888`, and sets
`SANDBOX_KERNEL_NAME=docsgpt-python` on them (the runner only ships the
kernelspec; the app chooses it) plus the shared `SANDBOX_GATEWAY_AUTH_TOKEN`. In
k8s these are added to the `docsgpt-api` and `docsgpt-worker` deployments when
enabling the opt-in `sandbox-deploy.yaml` (the default `docsgpt-deploy.yaml`
omits them); see that manifest's header for the exact env and the token Secret.

## Artifact rendering on Daytona (snapshot)

The `artifact` tool renders `presentation` / `document` / `spreadsheet` / `pdf`
specs by running a fixed renderer **inside the sandbox** that imports
`python-pptx`, `python-docx`, `openpyxl`, and `reportlab` (HTML/markdown need no
library). The self-hosted Jupyter runner inherits these from the backend venv,
but Daytona's default snapshot is a plain Python image — so under
`SANDBOX_BACKEND=daytona` those renders fail with `render failed: ExecutionError`
(a `ModuleNotFoundError` raised inside the sandbox). HTML/markdown still work.

Bake the libraries into a Daytona snapshot once, then point `DAYTONA_SNAPSHOT`
at it:

```bash
# Reads DAYTONA_API_KEY / DAYTONA_API_URL / DAYTONA_TARGET from .env:
python scripts/build_daytona_snapshot.py        # builds "docsgpt-artifacts-py312"
# then in .env:
#   DAYTONA_SNAPSHOT=docsgpt-artifacts-py312
```

The snapshot lives in **your** Daytona account, so each deployment builds its
own — the script is idempotent and skips if the name already exists. Keep the
pins in `scripts/build_daytona_snapshot.py` in sync with the backend venv so the
Daytona render output matches the Jupyter-backend output.

## Document reading (parsing worker — not the sandbox)

Document reading no longer runs in this sandbox. The `read_document` tool and the
workflow native-file extract branch enqueue a `parse_document` Celery task that
parses the document **in the backend** (Docling, already in
`application/requirements.txt`) and awaits the result. The task is routed to a
dedicated **`parsing` queue** (`settings.DOCUMENT_PARSE_QUEUE`, default
`"parsing"`) so a parse enqueued from inside a Celery worker (headless/scheduled
agent) is served by a separate worker and never self-deadlocks the awaiting one.

Run a dedicated parsing worker that consumes the `parsing` queue:

```bash
celery -A application.app.celery worker -Q parsing -l INFO
```

It can be GPU-enabled with its own env (`DOCLING_OCR_ENABLED=true` plus GPU
libraries) so OCR-heavy parsing runs on a separate, optionally larger pool.

**Dev / single-worker setups:** without a dedicated parsing worker the default
worker must also consume `parsing`, or the tool's await never resolves:

```bash
celery -A application.app.celery worker -Q docsgpt,parsing -l INFO
```

Tuning settings: `DOCUMENT_PARSE_TIMEOUT` (seconds the tool awaits before
degrading to an error), `DOCUMENT_PARSE_MAX_BYTES` (per-document byte cap; 0
reuses `SANDBOX_MAX_INPUT_BYTES`).

## Network egress / SSRF

The runner allows **broad outbound egress** (so sandboxed code can `pip install`
and call public APIs) but private, link-local, and cloud-metadata ranges **MUST
be blocked at the network layer**. This is not optional: the sandbox executes
arbitrary LLM-authored code, which opens its own sockets — app-level URL checks
(the `mcp_tool.py` approach) cannot contain it. Without a network-layer block,
sandbox code can reach `169.254.169.254` (cloud instance metadata / credentials)
and internal services on the private network.

The hardened container runs **without `NET_ADMIN`**, so it cannot self-apply
`iptables`. Enforcement therefore lives in deployment config:

- **Kubernetes** — apply
  [`deployment/k8s/network-policies/sandbox-egress-policy.yaml`](../k8s/network-policies/sandbox-egress-policy.yaml).
  It allows `0.0.0.0/0` egress with `except` carve-outs for RFC1918
  (`10/8`, `172.16/12`, `192.168/16`), link-local (`169.254/16`, which contains
  `169.254.169.254`), loopback, CGNAT, documentation/test ranges, and the IPv6
  ULA/link-local equivalents — and restricts ingress to the API/worker pods on
  TCP 8888. It requires a policy-enforcing CNI (Calico, Cilium, …); plain
  flannel/kube-proxy will silently not enforce it. The matching sandbox pod is
  [`deployment/k8s/deployments/sandbox-deploy.yaml`](../k8s/deployments/sandbox-deploy.yaml)
  (label `app: docsgpt-sandbox`).

  ```bash
  kubectl apply -f deployment/k8s/deployments/sandbox-deploy.yaml
  kubectl apply -f deployment/k8s/network-policies/sandbox-egress-policy.yaml
  ```

- **docker-compose** — compose cannot express L3 egress filtering natively. The
  sandbox overlay reaches the runner over an `internal: true` control network
  (`sandbox-net`, no host port) and gives it internet egress on a dedicated
  `sandbox-egress` bridge — but that bridge does not by itself block the metadata
  IP or RFC1918. Apply
  [`deployment/optional/docker-compose.optional.sandbox-egress.yaml`](../optional/docker-compose.optional.sandbox-egress.yaml),
  which flips `sandbox-egress` to `internal: true` (removing the runner's direct
  internet/RFC1918/metadata route entirely) and forces egress through a
  deny-private **egress-gateway proxy** sidecar. That `internal` flip is what
  contains **raw sockets to the internet/host/RFC1918/metadata** (a forward proxy
  only filters code that honors `HTTP(S)_PROXY`).

  **What compose canNOT contain:** the runner stays on `sandbox-net` with the
  backend and worker — that is its control path, and a shared Docker network is
  bidirectional, so Compose cannot sever it one-directionally. Sandbox code can
  therefore still open sockets to `backend:7091` and the worker. This is a real
  gap the Kubernetes NetworkPolicy closes (via its RFC1918 egress carve-out) but
  compose cannot. **Mitigate it** when enabling the sandbox: run the backend with
  real authentication (`AUTH_TYPE` != none / a real auth provider) so a reachable
  API rejects unauthenticated requests — **required** — and/or add a host-firewall
  `DROP` for runner→backend/worker on `sandbox-net` (see approach (1) in the
  overlay file's header comment). The runner is not on the `default` network, so
  it has no Docker-DNS route to redis/postgres; if the broker/DB publish host
  ports on a cloud VM, also apply the egress overlay (its `internal` flip removes
  the runner's route to the host gateway / RFC1918) or bind those ports to
  `127.0.0.1`.

## Other hardening (deployment-level)

The gVisor `runsc` runtime (kernel isolation for untrusted code), seccomp
profile, read-only root FS, non-root, and cgroup CPU/mem/PID caps (wired from
`SANDBOX_MEMORY` / `SANDBOX_CPUS`) are deployment-level concerns. The compose
service in `deployment/optional/docker-compose.optional.sandbox.yaml` already
sets `read_only`, `mem_limit`, `cpus`, and `pids_limit`; the k8s
`sandbox-deploy.yaml` sets the
equivalent `securityContext` + resource limits and has a commented
`runtimeClassName: gvisor` to enable on nodes with the `runsc` RuntimeClass
installed. These complement — they do not replace — the network egress policy
above.
