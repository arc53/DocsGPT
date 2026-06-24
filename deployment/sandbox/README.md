# docsgpt-sandbox runner

Always-on Jupyter Kernel Gateway that executes sandboxed LLM code. The DocsGPT
backend/worker is the **client** and connects over HTTP + WebSocket via
`SANDBOX_GATEWAY_URL`. Each session is an **in-process kernel** (child process),
never a child container; the Docker socket is **not** mounted.

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

A bare-venv gateway uses the **stock** `python3` kernelspec, which inherits the
gateway's full env (no secret scrubbing). The default `SANDBOX_KERNEL_NAME` is
`python3`, so plain venv dev gets no scrubbing — acceptable for single-trust
dev. The Docker image instead ships the env-scrubbing spec under the distinct
name `docsgpt-python` (see *Isolation model*) and the runner stack sets
`SANDBOX_KERNEL_NAME=docsgpt-python`. To get the scrubbing behavior in a venv,
copy `kernels/docsgpt-python/kernel.json` (pointing `argv` at a local copy of
`kernel-launch.sh`) into a Jupyter data dir on the kernelspec search path and
set `SANDBOX_KERNEL_NAME=docsgpt-python` before launching.

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
`http://docsgpt-sandbox:8888` and select the scrubbing kernel by setting
`SANDBOX_KERNEL_NAME=docsgpt-python` (the runner only ships the kernelspec; the
app chooses it). The same applies to k8s: `SANDBOX_KERNEL_NAME=docsgpt-python`
is set on the `docsgpt-api` and `docsgpt-worker` deployments in
`deployment/k8s/deployments/docsgpt-deploy.yaml`.

## Document extraction variant (Docling)

The `document_extractor` tool runs Docling (MIT) inside the runner to convert
documents (pdf/docx/pptx/...) to schema-validated JSON. Docling pulls `torch` and
ML models, which makes the image multi-GB, so it is **off by default**: it is not
in the base image, not in `application/requirements.txt`, and not required in the
dev `.venv`. Build the extract variant only where extraction is needed:

```bash
docker build -t docsgpt-sandbox-extract \
  --build-arg INSTALL_DOCLING=true deployment/sandbox
docker run --rm -p 8888:8888 docsgpt-sandbox-extract
```

Point the app at this runner via `SANDBOX_GATEWAY_URL` exactly as the base image.
Docling uses its own permissive PDF backend; **PyMuPDF (AGPL) is intentionally not
installed.** If the base (non-extract) image is used, `extract_document` returns a
clean "docling is not available in the sandbox runner" error rather than crashing.

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
  base stack puts the runner on an `internal: true` network (no host port), but
  that does not by itself block the metadata IP or RFC1918 reachable via the
  default bridge. Add a **host/cloud firewall rule** (drop the four private
  ranges on the sandbox container's interface) **or** route egress through an
  **egress-gateway proxy** sidecar. Both are documented in
  [`deployment/optional/docker-compose.optional.sandbox-egress.yaml`](../optional/docker-compose.optional.sandbox-egress.yaml).
  On untrusted/multi-tenant hosts prefer the host-firewall rule — a forward
  proxy only constrains code that honors `HTTP(S)_PROXY`.

## Other hardening (deployment-level)

The gVisor `runsc` runtime (kernel isolation for untrusted code), seccomp
profile, read-only root FS, non-root, and cgroup CPU/mem/PID caps (wired from
`SANDBOX_MEMORY` / `SANDBOX_CPUS`) are deployment-level concerns. The compose
service in `deployment/docker-compose.yaml` already sets `read_only`,
`mem_limit`, `cpus`, and `pids_limit`; the k8s `sandbox-deploy.yaml` sets the
equivalent `securityContext` + resource limits and has a commented
`runtimeClassName: gvisor` to enable on nodes with the `runsc` RuntimeClass
installed. These complement — they do not replace — the network egress policy
above.
