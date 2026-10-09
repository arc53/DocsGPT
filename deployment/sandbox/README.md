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
docker compose --env-file .env \
  -f deployment/docker-compose.yaml \
  -f deployment/optional/docker-compose.optional.sandbox.yaml up -d
```

Run it from the repository root. `--env-file .env` lets Compose read the root
`.env` for the `${...}` values, so the token can live there instead of in the
shell.

The token is **required** — the gateway fails closed if it is unset (see
*Gateway authentication* below). Add the egress-firewall overlay for SSRF
containment (see *Network egress / SSRF*):

```bash
docker compose --env-file .env \
  -f deployment/docker-compose.yaml \
  -f deployment/optional/docker-compose.optional.sandbox.yaml \
  -f deployment/optional/docker-compose.optional.sandbox-egress.yaml up -d
```

Then enable `code_executor` / `artifact_generator` **per-agent** in the agent
tool picker. Agents without them never call the runner, and the backend/worker
degrade gracefully when the runner is absent. The `-hub` compose variant takes
the same sandbox overlay. The egress overlay's proxy image is a placeholder:
replace it with your own deny-private forward proxy before using it (see
*Network egress / SSRF*). The user-facing guide is
[Code Execution Sandbox](https://docs.docsgpt.cloud/Deploying/Sandbox).

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
  re-execs ipykernel through `kernel-env.sh` under a minimal allowlisted env
  (`env -i` keeping only `PATH`, `LANG`, `JUPYTER_RUNTIME_DIR` and
  `JUPYTER_DATA_DIR`, plus a writable `HOME` and the image variables from
  `sandbox.env`; see *Kernel environment*). The image
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
docker run --rm -p 127.0.0.1:8888:8888 -e SANDBOX_GATEWAY_AUTH_TOKEN=devtoken docsgpt-sandbox
# in the app's .env:  SANDBOX_GATEWAY_URL=http://localhost:8888
#                     SANDBOX_GATEWAY_AUTH_TOKEN=devtoken
```

The published image `arc53/docsgpt-sandbox:<version>` (`develop` tracks main)
works the same way if you'd rather not build. The token is required — the
image's entrypoint refuses to start without it (see *Gateway authentication*). Without Docker (matches the test harness) you can run
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

The default `SANDBOX_KERNEL_NAME` is `docsgpt-python`, the env-scrubbing spec
the Docker image ships (see *Isolation model*). A bare-venv gateway has only
the **stock** `python3` kernelspec, so session creation fails until you do one
of these:

- Install the scrubbing spec: copy `kernels/docsgpt-python/kernel.json`
  (pointing `argv` at a local copy of `kernel-launch.sh`, with `kernel-env.sh`,
  `kernel-startup.py` and `sandbox.env` copied next to it) into a Jupyter data dir on the
  kernelspec search path. The default kernel name then works. Kernels get
  `HOME=/sandbox-home/home` when that mount exists and allows exec, otherwise
  `/tmp/home`, unless you set `SANDBOX_KERNEL_HOME` on the gateway.
- Or set `SANDBOX_KERNEL_NAME=python3` in the app's `.env`. The stock spec
  inherits the gateway's full env (no secret scrubbing), so use it only for
  single-trust dev.

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

## What the image contains

`docsgpt/sandbox/manifest.py` is the single list of what the sandbox holds. The
Daytona snapshot (`scripts/build_daytona_snapshot.py`) builds from it directly,
and `code_executor` tells the model what is installed from it. This image
installs from files generated from it, next to the Dockerfile:
`requirements.txt`, `install-system.sh`, `sandbox.env` and `manifest.json`.
Edit the manifest, never those files, then regenerate them (CI fails when they
are stale):

```bash
python scripts/export_sandbox_manifest.py
```

What is in it:

- **Python libraries:** pandas, numpy, matplotlib, openpyxl, python-docx,
  python-pptx, reportlab, lxml, Pillow, requests, beautifulsoup4, PyYAML, pypdf,
  PyPDF2, pdfplumber, pdfminer.six, pypdfium2, pytesseract and imageio, at the
  exact versions in the manifest.
- **Commands:** headless LibreOffice (`soffice`), headless Chromium
  (`chromium-headless-shell`), `tesseract` (English), poppler's `pdftotext`
  and `pdftoppm`, `ffmpeg` and `ffprobe`, and Node.js 24 (`node`, `npm`,
  `npx`) from the official nodejs.org tarball, checked against the SHA-256
  pinned in the manifest.
- **Helpers on PATH** (`helpers/`):
  - `office-convert FILE [--to pdf|docx|xlsx|pptx|png|...] [--outdir DIR]`
    runs LibreOffice with a throwaway profile per call (a shared profile makes
    a second soffice exit 0 having written nothing), a timeout, and a non-zero
    exit with a message when no output appears.
  - `html-to-pdf IN.html|URL OUT.pdf` and
    `html-screenshot IN.html|URL OUT.png [--width W --height H]` render with
    headless Chromium (`--no-sandbox --disable-gpu --disable-dev-shm-usage`,
    no PDF header or footer).
- **Fonts:** DejaVu, Liberation (Arial, Times New Roman and Courier New
  metrics), Carlito and Caladea (Calibri and Cambria metrics), Noto (Arabic,
  Devanagari, Hebrew, Thai and more) and Noto CJK.

imageio writes GIF and WebP through Pillow. It has no MP4 writer here, because
that needs the `imageio-ffmpeg` package, whose wheels bundle a static GPL
ffmpeg; code runs the `ffmpeg` command with `subprocess` for video instead.

### Licenses

The Python libraries, Node.js (MIT), Chromium (BSD-3-Clause) and tesseract
(Apache-2.0) are permissive. LibreOffice is MPL-2.0, and the fonts are under
the Bitstream Vera (DejaVu) and SIL OFL-1.1 licenses. Two packages are GPL:
poppler-utils and Debian's ffmpeg build. Both are unmodified Debian packages
that run only as separate programs, never linked into the Python code, and
Debian publishes their corresponding source (`apt-get source poppler ffmpeg`,
or sources.debian.org). PyMuPDF (AGPL) is deliberately not installed; use
pdfplumber, pypdf or pypdfium2.

### Kernel environment

The root filesystem is read-only (compose `read_only: true`, k8s
`readOnlyRootFilesystem`), so `kernel-env.sh` gives every kernel a writable
`HOME` and points `XDG_CONFIG_HOME`, `XDG_CACHE_HOME` and `PYTHONUSERBASE` into
it. LibreOffice, Chromium, fontconfig, npm and `pip install` (which falls back
to a user install, with its cache under `XDG_CACHE_HOME`) all write there. The
script also creates the user site-packages directory before the kernel starts,
so a package installed from a running kernel imports without a restart. All
sessions share that `HOME`, like the rest of the container (see *Isolation
model*).

Where `HOME` goes, first match wins:

1. `SANDBOX_KERNEL_HOME`, when set on the runner.
2. `/sandbox-home/home`, when `/sandbox-home` (`SANDBOX_HOME_MOUNT`) is a
   writable mount that is not `noexec`. The compose overlay mounts it as a
   tmpfs with `rw,exec,nosuid,nodev,size=${SANDBOX_HOME_SIZE:-1g},uid=10001,gid=10001,mode=0700`;
   the k8s manifest mounts a memory-backed `emptyDir` (1Gi `sizeLimit`), which
   is never `noexec`.
3. `/tmp/home` (`SANDBOX_TMP_HOME`), with one line on the gateway's stderr.

Docker mounts a compose `tmpfs:` entry `noexec,nosuid` unless told otherwise,
so a package with compiled code pip-installed under `/tmp/home` failed to load
with `failed to map segment from shared object`; pure-Python packages worked.
Under compose the separate home mount allows exec for that one directory only:
`/tmp`, where the session workspaces live, stays `noexec`, and `nosuid,nodev`
still refuse setuid binaries and device files. Both compose mounts are RAM and
count against the container's memory limit as they fill. On Kubernetes `/tmp` is
the `scratch` `emptyDir` (node disk, not `noexec`) and only `/sandbox-home` is
memory-backed, counting against the pod's memory limit. Either way kernel code
can already run anything through the Python interpreter, so exec on its own
home adds no new capability beyond loading the extensions it installed.

ipykernel sets `FORCE_COLOR=1` and `CLICOLOR_FORCE=1` once the kernel is up, so
Node, npm and pip coloured their output even into a pipe and the model read
escape codes. `kernel-launch.sh` runs `kernel-startup.py` in every kernel
(`--IPKernelApp.exec_files`), which drops both and sets `NO_COLOR=1`.

### Smoke test

`smoke_test.py` runs inside the image: it imports every manifest package,
checks every command and font, and converts real files (docx and pptx to PDF,
HTML to PDF and PNG, OCR, pdftotext, Node, an animated GIF and WebP, and an
H.264 MP4 checked with ffprobe). `--pip` also pip-installs a pure-Python
package and one with a compiled extension (`ujson`) and imports them, the
second in a new process. Run it the way kernels run, with the compose mounts:

```bash
docker build -t docsgpt-sandbox deployment/sandbox
docker run --rm --read-only --tmpfs /tmp \
  --tmpfs /sandbox-home:rw,exec,nosuid,nodev,size=1g,uid=10001,gid=10001,mode=0700 \
  docsgpt-sandbox \
  /opt/docsgpt/kernel-env.sh python /opt/docsgpt/smoke_test.py --pip
```

The `Verify the sandbox image` workflow runs the same command on every change
under `deployment/sandbox/`, then checks that the image without the home mount
falls back to `/tmp/home`.

For the Daytona snapshot, `python scripts/build_daytona_snapshot.py --smoke`
runs it in a sandbox made from the snapshot.

## Session lifetime

The app keeps a session's kernel between `run_code` calls, so variables, files
and installed packages carry over, and retires it once it has been idle for
`SANDBOX_MAX_TTL` seconds (1200 by default). Each process retires only its own
sessions, so a kernel held by an API or worker process that restarted would
otherwise live until the runner restarts. `gateway-launch.sh` therefore has the
gateway shut down any kernel idle for `SANDBOX_KERNEL_IDLE_TIMEOUT` seconds
(1800 by default); keep it above `SANDBOX_MAX_TTL`. The compose overlay passes
the variable through. A run's length does not add to it: a run may last up to
`SANDBOX_EXEC_MAX_TIMEOUT` seconds (1000 by default) when the model asks, but
the gateway never culls a busy kernel or one with an open connection, the app
never reaps a session while an exec holds it, and both idle clocks start again
when the run ends.

A kernel that dies mid-run (the container's OOM killer, usually) is restarted
by the gateway, which announces it on the kernel channel. The app ends the call
at once instead of waiting out the timeout, deletes the kernel (the restarted
process has lost the session's variables and working directory) and reports
"out of memory" when the container's OOM-kill counter (`memory.events`, or
`memory.oom_control` on cgroup v1) rose since the kernel started.

Warm kernels count against the runner's memory: an idle kernel takes about
50-60 MB, more once code has loaded data, and session workspaces live on the
`/tmp` tmpfs. A LibreOffice conversion takes about 170 MB more and a headless
Chromium render about 110 MB on small documents (more on large ones). Size
`SANDBOX_MEMORY` (4g by default; it was 1g before the image carried LibreOffice
and Chromium) for the conversations that run code at the same time, or lower
`SANDBOX_MAX_TTL`. Runtime pip installs live on the `/sandbox-home` tmpfs
(`SANDBOX_HOME_SIZE`, 1g by default) and count too. `SANDBOX_MAX_SESSIONS`
(32) caps each API and worker process on its own, not the runner as a whole,
so several processes at their cap can hold more warm kernels than 4g fits. The compose overlay also sets `shm_size: 256m` and
`pids_limit: 1024` for Chromium; the k8s manifest mounts a 256 Mi memory-backed
`/dev/shm` and limits memory to 4 Gi.

## Daytona snapshot

Daytona's default snapshot is a plain Python image: under
`SANDBOX_BACKEND=daytona` the `artifact` tool's presentation, document,
spreadsheet and PDF renders fail with `render failed: ExecutionError` (a
`ModuleNotFoundError` inside the sandbox), and none of the commands above
exist. `scripts/build_daytona_snapshot.py` builds a snapshot with the same
contents as this image from the same manifest, with 2 vCPU, 2 GiB RAM and 6 GiB
disk per sandbox (Daytona's default is 1/1/3):

```bash
# Reads DAYTONA_API_KEY / DAYTONA_API_URL / DAYTONA_TARGET from .env:
python scripts/build_daytona_snapshot.py          # builds "docsgpt-sandbox-py312-v3"
python scripts/build_daytona_snapshot.py --smoke  # and runs smoke_test.py in a sandbox from it
python scripts/build_daytona_snapshot.py --dockerfile  # prints the image; no API call
# then in .env:
#   DAYTONA_SNAPSHOT=docsgpt-sandbox-py312-v3
```

`--cpu`, `--memory` and `--disk` change the resources. A snapshot's contents
and resources are fixed once built, so a manifest change needs a new snapshot
name: snapshots from earlier versions of the script (`docsgpt-artifacts-py312`,
`docsgpt-sandbox-py312`) lack most of these tools. The snapshot lives in
**your** Daytona account, so each deployment builds its own; the script skips a
name that already exists.

## Document reading (parsing worker — not the sandbox)

Document reading no longer runs in this sandbox. The `read_document` tool and the
workflow native-file extract branch enqueue a `parse_document` Celery task that
parses the document **in the backend** (the `DOC_PARSER_ENGINE` parser — anydoc
by default; Docling only when the optional
`docsgpt/requirements-docling.txt` extra is installed) and awaits the
result. The task is routed to a
dedicated **`parsing` queue** (`settings.DOCUMENT_PARSE_QUEUE`, default
`"parsing"`) so a parse enqueued from inside a Celery worker (headless/scheduled
agent) is served by a separate worker and never self-deadlocks the awaiting one.

Run a dedicated parsing worker that consumes the `parsing` queue:

```bash
celery -A docsgpt.app.celery worker -Q parsing -l INFO
```

It takes its own env, so parse-heavy work runs on a separate, optionally larger
pool. A GPU helps it only with the docling extra installed
(`INSTALL_DOCLING=true`), whose layout and table models run on torch:
`OCR_ENABLED=true` alone keeps the CPU-only native backend with the default
`OCR_ENGINE=tesseract`, which GPU libraries do not accelerate. Setting
`OCR_ENGINE=deepseek` instead moves the OCR cost onto the Ollama/vLLM endpoint
or a hosted API (`OCR_DEEPSEEK_PROVIDER`) and leaves this worker light.

**Dev / single-worker setups:** a worker started without `-Q` already consumes
every configured queue, `parsing` included, so no extra flag is needed. Only if
you restrict queues with `-Q` must you include `parsing` (and `embeddings`) or
run a dedicated parsing worker, or the tool's await never resolves:

```bash
celery -A docsgpt.app.celery worker -B -Q docsgpt,parsing,embeddings -l INFO
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
sets `read_only`, `mem_limit`, `cpus`, `pids_limit` and `shm_size`; the k8s
`sandbox-deploy.yaml` sets the
equivalent `securityContext` + resource limits and has a commented
`runtimeClassName: gvisor` to enable on nodes with the `runsc` RuntimeClass
installed. These complement — they do not replace — the network egress policy
above.
