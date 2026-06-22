# Artifacts & Code Execution — Design Research & Proposal

> Status: research synthesis / design proposal (not yet implemented).
> Scope: an artifact + semi-persistent code-execution system for DocsGPT, covering
> (1) interactive document generation in chat and (2) file-passing across agentic workflows.
> Method: produced from a multi-agent investigation — three agents mapping the DocsGPT
> codebase (storage, tools, workflows/templating) and seven agents researching OSS prior art
> (E2B, Daytona, Modal, Jupyter, gVisor/Firecracker, LibreChat, Open WebUI, Vercel AI SDK,
> Claude Artifacts, OpenAI Canvas, llm-sandbox, MCP Resources).

---

## 1. Executive summary

Two product use cases drive this:

1. **Interactive document generation.** A user asks the assistant to generate a document
   (e.g. a `.pptx` via `python-pptx`), the file is rendered in a code executor, served back,
   and the user can **re-open and iteratively edit it** later.
2. **Agentic compliance/analysis workflows.** Multiple sub-agents receive documents, analyze
   them, hand files to **code-executor nodes** that parse and produce structured outputs, which
   downstream nodes use to make decisions.

The four building blocks the user identified map cleanly onto DocsGPT subsystems that mostly
already exist in skeleton form:

| # | Component | DocsGPT today | Verdict |
|---|-----------|---------------|---------|
| 1 | File/data storage | `BaseStorage` (local/S3) + `attachments` table | **Reuse + add an `artifacts` table** (the schema header at `models.py:274` literally names "artifacts" but it was never built) |
| 2 | Semi-persistent code execution | **Nothing** — no sandbox/executor tool exists | **Wrap `llm-sandbox` (MIT)** behind a pluggable `CodeSandbox` abstraction (gVisor runtime; E2B optional) |
| 3 | Extracting data from execution | Tools may return dicts; `get_artifact_id` hook + `/api/tools/artifact/<id>` exist but are hardcoded to notes/todos | **Generalize** the artifact-fetch path + add a real download endpoint |
| 4 | Templating to pass files around | Jinja2 `SandboxedEnvironment` + extensible `NamespaceManager`; workflow `state` blackboard | **Add an `artifacts.*` namespace + pass-by-reference convention** |

**The single most important architectural decision** (validated by every mature system we
studied — LangGraph, OpenAI, CrewAI, AutoGen, LibreChat): **pass artifacts by reference, never
by value.** Binary bytes never travel through LLM context, workflow `state`, or message bodies —
only a small handle (`artifact_id` / URI + metadata) does, and the bytes are fetched on demand.

**The single most important UX decision** (from Gamma, SlideDeck-AI, JSON2PPT): for *editable*
generated documents, **store a structured spec (JSON/Markdown) as the source of truth and treat
the rendered binary as a derived artifact.** "Edit the deck" = mutate the spec + re-render
deterministically, not patch a `.pptx` in place.

---

## 2. What DocsGPT has today (grounded reality)

### 2.1 Storage layer — reusable, with gaps
- `application/storage/base.py` defines `BaseStorage` with `save_file / get_file / process_file /
  delete_file / file_exists / list_files / is_directory / remove_directory`. Backends:
  `LocalStorage` (`local.py`), `S3Storage` (`s3.py`), selected via `STORAGE_TYPE` through the
  process-wide singleton `StorageCreator.get_storage()` (`storage_creator.py:18`).
- **`process_file(path, processor_func)` hands a callback a real local filesystem path**
  (`base.py:41`; S3 downloads to a `NamedTemporaryFile` first, `s3.py:176`). This is *exactly*
  the primitive a code executor needs to feed a file to a subprocess/kernel.
- The **`attachments`** table (`models.py:386`, repo `repositories/attachments.py`) is the closest
  existing "artifact": user-owned blob registry with `upload_path`, `mime_type`, `content`
  (extracted text), `metadata` JSONB, and a **provider-handle cache** (`openai_file_id`,
  `google_file_uri`) updated via `update_any` — a working precedent for "store a handle, reuse it."
- Storage key convention: `inputs/{user}/attachments/{uuid}/{filename}` (`attachments/routes.py:165`).

**Gaps:** no `artifacts` table; no versioning/lineage on attachments (`created_at` only); `get_file`
reads whole objects into memory (no streaming/range); **no signed URLs** (`URL_STRATEGY=s3`
emits *public* URLs, `utils.py:200`); **no authenticated, storage-agnostic, `Content-Disposition`
download endpoint** (`/api/images/...` is inline-only and unauthenticated; `/api/download` is
local-disk-only + internal-key-gated); `size` column exists but is never populated; no per-session
workspace concept.

### 2.2 Tools & execution — strong hooks already present
- `Tool` ABC is tiny (`tools/base.py`): `execute_action`, `get_actions_metadata`,
  `get_config_requirements`. **Auto-discovery**: dropping `tools/code_executor.py` with a
  non-internal `Tool` subclass registers it with zero wiring (`tool_manager.py:15`).
- Per-user/per-conversation instantiation is available by adding a tool name to the allowlists in
  `tool_manager.py:31-48`; `conversation_id` and `tool_id` are already injected into `tool_config`
  (`tool_executor.py:885`). **This is the hook for per-conversation sandboxes.**
- Tools may return structured dicts; results are JSON-serialized into context with
  `PGNativeJSONEncoder` (bytes→base64) (`openai.py:56`). **But binary has no real transport** — UI
  events and the persisted summary are truncated to a 50-char preview (`tool_executor.py:785`).
- **Artifact rail already exists (and is the key reuse):** a tool can implement
  `get_artifact_id(...)`; the executor attaches `artifact_id` to the tool-call event + the
  `tool_call_attempts` journal (`tool_executor.py:762`), and **the frontend already renders an
  "open artifact" affordance** (`ConversationBubble.tsx:445`, `ArtifactSidebar.tsx`). But the fetch
  endpoint `GET /api/tools/artifact/<id>` is **hardcoded to notes/todos** (`tools/routes.py:850`).
- **Approval / human-in-the-loop is reusable for gating code exec:** static `require_approval` on
  an action (`remote_device.py:72`) or dynamic `preview_decision` (`tool_executor.py:475`,
  `529-553`) → full pause/resume via `pending_tool_state` + out-of-band notification, for free.
- **MCP**: `mcp_tool.py` wraps FastMCP over HTTP/SSE (STDIO disabled, `mcp_tool.py:216`), with SSRF
  validation that rejects private addresses (`mcp_tool.py:95`). A remote sandbox *can* be an MCP
  server, auto-discovered and auth-handled — but MCP-returned binaries still don't become fetchable
  artifacts today.

**Gaps:** no harness-level timeout/resource limits (each tool self-limits); no streaming/incremental
tool output (`execute_action` is blocking, only `pending`→`completed` events); generic artifact
persistence absent (notes/todos are FK-bound to `user_tools.id`).

### 2.3 Workflows & templating — linear blackboard, extensible templates
- Workflow execution is a **single-pointer linear walk** over a shared mutable `state` dict
  (`workflow_engine.py:46`), capped at 50 steps; the only branching is `condition` nodes evaluated
  via **CEL** (`cel_evaluator.py`). Node types are fixed: `start, end, agent, note, state, condition`
  (`schemas.py:8`). Agent-node output is written to `state["node_<id>_output"]` and an optional
  `output_variable` alias (`workflow_engine.py:311`); downstream nodes read it via Jinja templates
  (`agent.*` namespace) or CEL.
- Persistence: a `workflow_runs` row stores the entire final `state` + per-step `state_snapshot`
  as JSONB, but `_serialize_state_value` **stringifies any non-primitive** (`workflow_agent.py:253`)
  — so files cannot durably ride along; only a *string* handle can.
- **Sub-agents exchange text/JSON only** — they inherit scalar config + a shared `chat_history`
  reference but **not** `state`, and there is **no shared file workspace** (`node_agent.py`,
  `workflow_engine.py:241-315`). `ResearchAgent.parallel_workers` is dead config — research is
  sequential (`research_agent.py:117,127`).
- Templating is **Jinja2 `SandboxedEnvironment`** (`templates/template_engine.py:21`) with an
  **extensible `NamespaceManager`** (`templates/namespaces.py:154`): `system.*`, `passthrough.*`,
  `source.*`, `tools.*`, plus `agent.*` in workflows. Namespaces deliberately **drop
  non-serializable values** — there is no `file()`/`artifact()` accessor today.
- **Versioning precedent:** `workflows.current_graph_version` with atomic increment
  (`workflows.py:103`) — mirror this for artifact versions.

**Gaps for use case 2:** linear engine (no fan-out/join → can't express "N sub-agents analyze in
parallel, then combine"); no shared workspace; no file/artifact type in `state`; templates can't
reference files.

---

## 3. OSS prior art (condensed)

### 3.1 Code-execution sandboxes
| Project | Isolation | Persistence | Self-host | License |
|---|---|---|---|---|
| **E2B** | Firecracker microVM | pause/resume (mem+FS), reattach by id, 5min→24h, 30-day snapshot TTL | **Yes** (`e2b-dev/infra`, needs KVM hosts) | **Apache-2.0** ✅ |
| **llm-sandbox** | pluggable Docker/K8s/Podman | interactive sessions keep kernel state; "artifact sessions" auto-capture plots | **Yes** (library) | **MIT** ✅ |
| **microsandbox** | libkrun microVM | per-agent microVMs via a server you run | **Yes** (self-host only) | **Apache-2.0** ✅ |
| **Jupyter Kernel Gateway** | none alone (wrap in container/gVisor) | **stateful kernel**: vars/imports/cwd persist across executions; reattach by kernel id over HTTP/WS; Enterprise Gateway adds per-user namespaces + idle culling | **Yes** | **BSD-3** ✅ |
| **Daytona** | Sysbox container | snapshots, auto-stop 15min | Yes | **AGPL-3.0** ⚠️ |
| **Modal / Azure ACA / Cloudflare** | gVisor / Hyper-V / container-in-VM | strong, but **not self-hostable** | No | proprietary ⚠️ |
| **Riza** | WebAssembly | stateless | Yes (licensed) | proprietary ⚠️ |

Isolation building blocks (all Apache-2.0): **gVisor** (user-space kernel, what Modal/ChatGPT-CI/
Anthropic reportedly use; 10–40% syscall / 30–80% FS overhead, ms start), **Firecracker** (microVM,
~125ms boot, <5MiB overhead), **nsjail**, **Kata**, **libkrun**. Plain `docker exec` shares the host
kernel and is **not** a security boundary for untrusted multi-tenant code.

### 3.2 Artifact UX & data models
- **Vercel AI Chatbot (Apache-2.0)** — the most directly borrowable schema. `Document { id uuid
  (NOT unique alone), createdAt, title, content, kind enum, userId }` with **composite PK
  `(id, createdAt)`**: same `id` = stable identity, each `createdAt` row = an immutable version.
  Edits **append** a new row; revert = delete rows after a timestamp. Three tools drive it:
  `createDocument`, `updateDocument` (**full rewrite**), `editDocument` (**targeted
  `old_string`/`new_string`** — "preferred for small changes"). Streams content live as typed
  `data-textDelta` parts; 2s debounced auto-save.
- **LibreChat (MIT)** — closest analog to DocsGPT. Two paths: (A) model-emitted `:::artifact{
  identifier, type, title}` directives embedded in message text, rendered in a **sandboxed iframe
  (Sandpack)**; "editing" = exact-string replace in the message text; versioning = ordered list in
  memory. (B) **Tool artifacts** = files produced by code execution, classified by MIME with preview
  types incl. `…docx-preview`, `…spreadsheet-preview`, `…presentation-preview`. **Code-interpreter
  file persistence is the pattern to copy:** sandbox output → download → save via storage strategy →
  `File` doc with `metadata.codeEnvRef = {kind, id, storage_session_id, file_id}` → on later turns
  `primeFiles()` **re-mounts the bytes into a fresh sandbox session**, rewriting `storage_session_id`.
  Code-env files carry a **1-hour TTL** (`expiresAt`).
- **Claude Artifacts / OpenAI Canvas** — converge on: a side panel (preview + code), a **version
  selector with restore + diff**, and **targeted edit vs full rewrite** (Canvas was trained to patch
  on text-selection, rewrite otherwise; Claude reportedly uses `old_str`/`new_str`). Claude exposes a
  persistent **artifacts sidebar/gallery**; "every publish is a new version at the same link."
- **Open WebUI** — renders HTML/SVG/JS in an **`<iframe srcdoc>` with `sandbox="allow-scripts …"`
  (same-origin OFF by default) + injected CSP** (`IFRAME_CSP`). Note its license is now a custom
  **"Open WebUI License" (source-available, NOT OSI/MIT)** for v0.6.6+ — **clean-room only; do not
  copy current code.** (≤ v0.6.5 was BSD-3.)

### 3.3 Inter-node / sub-agent file passing
Every framework converges on **pass-by-reference**: LangGraph keeps blobs in object storage / a
`BaseStore` and only a URL/metadata in `state` (inlining a 50MB PDF → checkpointer re-writes it
every step → 500MB); CrewAI `Task.output_file` (path) + structured `output_pydantic`; AutoGen shares
a `work_dir`; OpenAI passes `file_id`s + `container_file_citation` annotations. **MCP Resources** are
the protocol-standard addressing mechanism: `resources/list` + `resources/read` return `contents[]`
with a `uri`, `mimeType`, and **either `text` or base64 `blob`** — agents hold the URI, materialize
bytes on demand; `resourceTemplates` (RFC 6570) + `resources/subscribe` for parameterized/live ones.

### 3.4 Document libraries (Python, license-checked)
Safe (MIT/BSD): **python-pptx, python-docx, openpyxl** (MIT); **XlsxWriter, WeasyPrint, ReportLab,
pandas** (BSD); **matplotlib**; **Quarto/Marp, Docling** (MIT). Flags: **PyMuPDF — AGPL** ⚠️ (avoid
or buy Artifex license); **Pandoc — GPL** (only as an external CLI subprocess); **fpdf2 — LGPL**;
**Unstructured** core Apache-2.0 but feature-gated. For compliance extraction, prefer **Docling**
(MIT, local, strong tables, bank-targeted) → schema-validated JSON.

---

## 4. Proposed design

### Component 1 — Artifact store + data model

Add the long-anticipated `artifacts` entity. Model it on Vercel's append-only versioning, adapted
to DocsGPT conventions (UUID PK, `user_id TEXT`, JSONB `metadata`, alembic migration, repository
class, `legacy_mongo_id` omitted — this is new).

```
artifacts                      -- identity row (one per logical artifact)
  id              UUID  PK
  user_id         TEXT  NOT NULL
  conversation_id UUID  NULL        -- use case 1 (chat-scoped)
  workflow_run_id UUID  NULL        -- use case 2 (run-scoped)
  message_id      UUID  NULL        -- soft link to producing message
  kind            TEXT  NOT NULL    -- 'document' | 'spreadsheet' | 'presentation'
                                    -- | 'code' | 'html' | 'image' | 'data' | 'file'
  title           TEXT
  current_version INT   NOT NULL DEFAULT 1   -- mirrors workflows.current_graph_version
  created_at / updated_at

artifact_versions              -- append-only; never mutated
  id              UUID  PK
  artifact_id     UUID  FK -> artifacts.id  (ON DELETE CASCADE)
  version         INT   NOT NULL            -- UNIQUE(artifact_id, version)
  mime_type       TEXT
  filename        TEXT
  storage_path    TEXT                      -- key in BaseStorage (NULL if spec-only)
  size            BIGINT
  sha256          TEXT
  spec            JSONB                      -- "source of truth" for editable docs (see C-edit)
  preview_text    TEXT                       -- extracted text / summary for LLM context
  produced_by     JSONB                      -- {tool_id, action, node_id, session_id}
  created_at
```

- **Identity vs version:** `artifacts.id` is the stable handle passed around; each edit appends an
  `artifact_versions` row and bumps `current_version` (atomic increment, exactly like
  `workflows.increment_graph_version`, `workflows.py:103`). Revert = point `current_version` back.
- **Pass-by-reference everywhere:** the only thing that enters LLM context / workflow `state` /
  message bodies is `{artifact_id, version, mime_type, filename, size}`. Bytes live in `BaseStorage`.
- **Storage key convention:** `inputs/{user}/artifacts/{artifact_id}/v{version}/{filename}` — reuses
  the existing per-UUID directory pattern and the `BaseStorage` backends unchanged.
- **`AttachmentsRepository` is the template** for the new `ArtifactsRepository` (create/get/
  resolve_ids/update + `_to_dict` aliasing). Same encryption/redaction discipline.

### Component 2 — Semi-persistent code executor

**Decision (chosen): wrap `llm-sandbox` (MIT) as the default backend**, behind a thin
DocsGPT-owned abstraction (mirroring `StorageCreator`) so other backends stay pluggable.

```
application/sandbox/
  base.py        CodeSandbox ABC:
                   open(session_id) / attach(session_id) / close(session_id)
                   exec(code, libraries=None, timeout=...) -> ExecResult
                       ExecResult = {stdout, stderr, exit_code, plots[], display_data}
                   put_file(src, dest) / get_file(path) -> bytes / list_files()
  manager.py     SandboxManager: warm pool + {session_id -> container} registry + idle reaper
  llm_sandbox.py #1 DEFAULT  — wraps llm-sandbox (MIT)
  e2b.py         #2 OPTIONAL — E2B backend (Apache-2.0) for Firecracker-grade isolation
  (backend selected via SANDBOX_BACKEND in application/core/settings.py)
```

**Why `llm-sandbox` is the right default (verified against its API):** it is MIT, pure-Python, and
already exposes every primitive the abstraction needs — so we *wrap*, we don't build.

| DocsGPT need | `llm-sandbox` primitive |
|---|---|
| Stateful kernel (vars/imports persist across executions) | `InteractiveSandboxSession(lang="python", kernel_type="ipython")` — `run()` keeps state; supports `%pip install` |
| Auto-capture generated charts/files | `ArtifactSandboxSession` → `result.plots[]` (`content_base64`, `format`) |
| Run code + install deps; run shell | `session.run(code, libraries=[...])` → `{stdout, stderr, exit_code}`; `session.execute_command(cmd)` |
| Files in/out (artifact store ↔ workspace) | `session.copy_to_runtime(host, sandbox)` / `session.copy_from_runtime(sandbox, host)` |
| Warm pool + idle reaping | `create_pool_manager(backend, PoolConfig(max_pool_size, min_pool_size, idle_timeout, max_container_lifetime, max_container_uses), lang)` |
| Swap isolation without code change | `backend="docker" \| "kubernetes" \| "podman"` (+ remote Docker via custom client) |
| Resource / security caps | per-container `SANDBOX_MEMORY`, `SANDBOX_CPUS`, `SANDBOX_NETWORK_MODE`, `SANDBOX_READ_ONLY`, `SANDBOX_CAP_DROP`, `SANDBOX_SECURITY_OPT` |
| Multi-language (compliance scripts, JS, …) | Python, JS/Node, Java, C++, Go, R, Ruby via `lang=` |

**Isolation note:** `llm-sandbox` delegates isolation to its backend. For multi-tenant DocsGPT, run the
Docker/Podman backend under the **gVisor `runsc` runtime** (Apache-2.0) — or the Kubernetes backend
with a gVisor `RuntimeClass` — so untrusted LLM code never touches the host kernel. This keeps the MIT
wrapper while getting near-microVM isolation with ordinary container ergonomics and ops.

`llm-sandbox` also ships an **MCP-server mode** (`pip install 'llm-sandbox[mcp-docker]'`), so a remote
deployment could plug into DocsGPT's existing MCP path instead of running in-process — but in-process
(library) is the default and simplest.

**`SandboxManager` is the only meaningful code we write for C2:** it wraps `create_pool_manager`, keys
a `{session_id -> container}` registry on `conversation_id` (chat) or `workflow_run_id` (workflow), and
adds the persist-on-reap policy (below). Everything else is delegated to `llm-sandbox`.

**Alternative backends (pluggable, not default):** **E2B** (Apache-2.0, self-host) for Firecracker-grade
isolation + memory pause/resume where KVM hosts exist; **microsandbox** (Apache-2.0, libkrun) as another
hardware-isolation option. **Avoid embedding Daytona / open-interpreter (AGPL).**

**Session lifecycle (semi-persistent):**
`POST allocate` (from a small **warm pool**) → bind a `sessionId` to `conversation_id` (chat) or
`workflow_run_id` (workflow) → all executions route to that sandbox; **reattach by id** on reconnect →
**idle-reap after ~10–20 min**, but **persist-on-reap**: flush workspace files to the artifact store
(don't just kill) → on next access, spin a fresh kernel and **re-mount artifacts by reference**
(LibreChat `codeEnvRef`/`primeFiles` pattern) → **hard destroy at a 24h cap or on conversation
delete**. A `keepAlive` ping covers long workflow jobs.

**Integration into DocsGPT:**
- As a **tool**: `tools/code_executor.py` (auto-registers via `tool_manager`); add its name to the
  per-user allowlists (`tool_manager.py:31-48`) so it receives `user_id`/`conversation_id`; gate it
  with `require_approval`/`preview_decision` (reuse the `remote_device` pattern); enforce its **own**
  wall-clock timeout; stream incremental status events.
- As a **workflow node**: add a `code` node type to `NodeType` (`schemas.py:8`) handled by the
  engine, bound to the run's `sessionId`. (Reuse `ToolFilterMixin` to scope tools.)
- Optionally as an **MCP server** (HTTP/SSE) for remote/external executors — but note the SSRF
  validation (`mcp_tool.py:95`) and that an MCP→artifact bridge must be added.

**Security checklist (executing untrusted LLM code):** gVisor/microVM isolation (never default
docker for multi-tenant); **default-deny network egress** + hostname allowlist via a proxy that
injects credentials the sandbox never sees; read-only root FS + a single quota'd scratch dir;
cgroup CPU/mem/PID caps + per-exec timeout + max lifetime; seccomp profile, drop capabilities,
no-new-privileges, non-root UID; one sandbox per tenant/session (never reuse a warm sandbox across
tenants without reset); treat all sandbox output as untrusted (render HTML/SVG only in a sandboxed
iframe + CSP; schema-validate structured outputs before any decision logic consumes them).

### Component 3 — Extracting data from execution

- The executor tool returns a **compact structured payload**, never raw bytes:
  ```json
  { "status": "ok", "stdout_tail": "...", "structured": { ... },
    "artifacts": [ {"artifact_id": "…", "version": 2, "filename": "deck.pptx",
                    "mime_type": "…", "size": 91234} ] }
  ```
  and sets `get_artifact_id()` so the existing UI rail lights up.
- **Generalize `GET /api/tools/artifact/<id>`** (`tools/routes.py:850`) beyond notes/todos: add a
  `"document"`/`"file"` branch backed by `ArtifactsRepository`, returning metadata + a download URL.
- **Add the missing download endpoint:** authenticated, storage-agnostic, `Content-Disposition:
  attachment`, per-user authz, backed by `BaseStorage.get_file` — and add `generate_presigned_url`
  to the S3 backend so private artifacts aren't proxied through the web worker (and aren't public).
- **Compliance (use case 2):** code nodes emit JSON validated against a node `json_schema` using the
  **existing** `jsonschema` path (`workflow_engine.py:381`). Use **Docling (MIT)** for extraction.
  Capture structured kernel values scrapbook-style (analogous to OpenAI `container_file_citation`).

### Component 4 — Templating / passing files around

- **Add an `artifacts.*` namespace** to `NamespaceManager` (`namespaces.py:157`) — a single new
  `NamespaceBuilder`, automatically available to both the prompt renderer and the workflow engine
  (both call `build_context`). Expose `{{ artifacts.<name>.id }}`, `.mime_type`, `.filename`, plus an
  `artifact(id)` helper. Resolve names from `output_variable`s that hold artifact references.
- **Workflow passing = the existing `state` blackboard, carrying references.** A code node writes
  `state["report"] = {"artifact_id": …}` (a JSON-primitive, so it survives `_serialize_state_value`),
  and a later node/code-executor re-fetches by id. No engine change needed for the happy path; this
  is the pass-by-reference rule applied to the current design.
- **Expose artifacts as MCP Resources** (`uri`, `mimeType`, `text|blob`) so sub-agents and external
  MCP clients `resources/read` on demand — the standard cross-agent addressing mechanism.
- **CEL** can already branch on artifact metadata (it indexes nested dicts) — e.g.
  `report.size > 0 && report.mime_type == "application/pdf"`.

---

## 5. Editable-artifact strategy (use case 1)

**Store-a-spec, re-render.** For generated documents, the `artifact_versions.spec` JSONB is the
source of truth; the `.pptx`/`.docx`/`.pdf` is derived by the code executor on each change. This is
what Gamma/SlideDeck-AI/JSON2PPT do and it gives clean, diffable, deterministic version history.

Drive edits with a **three-verb model** (Vercel/Claude/Canvas all converge here):
- `create_artifact(kind, spec)` → render → store v1.
- `edit_artifact(id, instruction)` → LLM mutates the **spec** (targeted change) → re-render → append
  version. Prefer this for small changes.
- `rewrite_artifact(id, spec)` → full replacement → append version.

Frontend: DocsGPT already has `ArtifactSidebar.tsx`; extend it with a version selector + download +
(for HTML/SVG/Mermaid kinds) a **sandboxed `<iframe srcdoc>` + CSP** preview (Open WebUI/LibreChat
pattern — clean-room, not copied). Office docs render as a download/preview card.

---

## 6. End-to-end flows

**Use case 1 (chat → editable deck):**
1. User: "make a 5-slide deck on Q3 results." LLM calls `code_executor` (or `create_artifact`).
2. LLM emits a slide **spec** (JSON); the executor runs `python-pptx` in the session, writes
   `deck.pptx` to the workspace.
3. Backend persists `artifacts` row + `artifact_versions` v1 (`spec` + `storage_path` + sha256);
   tool returns `{artifact_id, …}`; `ArtifactSidebar` shows preview + download.
4. User: "make the title bigger and add a chart." LLM calls `edit_artifact` → mutates spec →
   re-render → v2 appended. User can diff/restore versions, re-open weeks later (chat-scoped id).

**Use case 2 (compliance workflow):**
1. Documents enter a workflow run; the run gets a `sessionId`-bound sandbox.
2. Parallel-ish sub-agent nodes extract/analyze (Docling → schema JSON) and write **artifact
   references** into `state` (`output_variable`s).
3. A **code node** re-fetches those artifacts into the sandbox, parses/cross-checks them, emits a
   schema-validated decision object + a generated report artifact (by reference).
4. A `condition` node branches on the JSON (CEL); `end` node renders the outcome.
   *(Requires the fan-out/join gap below for true parallelism.)*

### 6.1 Sequence — use case 1 (chat → editable deck)

```mermaid
sequenceDiagram
    actor U as User
    participant FE as Frontend (ArtifactSidebar)
    participant API as Answer/Stream API
    participant AG as Agent + LLM
    participant TX as code_executor tool
    participant SB as SandboxManager (llm-sandbox)
    participant ART as ArtifactsRepository
    participant ST as BaseStorage

    U->>API: "make a 5-slide deck on Q3"
    API->>AG: stream turn
    AG->>TX: create_artifact(kind="presentation", spec=JSON)
    TX->>SB: attach(session=conversation_id)
    TX->>SB: exec(python-pptx render from spec)
    SB-->>TX: copy_from_runtime("/work/deck.pptx")
    TX->>ST: save_file(inputs/{u}/artifacts/{aid}/v1/deck.pptx)
    TX->>ART: create artifact + version v1 (spec, path, sha256)
    TX-->>AG: {artifact_id, version:1, mime, size}  (no bytes)
    AG-->>API: tool_call event w/ artifact_id
    API-->>FE: SSE: artifact_id
    FE->>API: GET /api/artifacts/{id}/download
    FE-->>U: preview + download
    U->>API: "make the title bigger, add a chart"
    AG->>TX: edit_artifact(id, instruction) — mutate spec
    TX->>SB: exec(re-render from spec)
    TX->>ART: append version v2; current_version=2
    FE-->>U: version selector (v1|v2), diff, restore
```

### 6.2 Sequence — use case 2 (compliance workflow, by reference)

```mermaid
sequenceDiagram
    participant WF as WorkflowEngine
    participant N1 as Analyst node (doc A)
    participant N2 as Analyst node (doc B)
    participant CN as code node
    participant SB as SandboxManager (run-scoped)
    participant ART as ArtifactsRepository
    participant CD as condition node

    Note over WF: state = blackboard of references (ids), never bytes
    WF->>N1: analyze A (Docling -> schema JSON)
    N1->>ART: store extract A
    N1-->>WF: state["a"] = {artifact_id}
    WF->>N2: analyze B
    N2->>ART: store extract B
    N2-->>WF: state["b"] = {artifact_id}
    WF->>CN: code node (inputs: state.a, state.b)
    CN->>SB: attach(session=workflow_run_id)
    CN->>ART: fetch a, b
    CN->>SB: copy_to_runtime(a,b); exec(cross-check); copy_from_runtime(report)
    CN->>ART: store decision JSON + report artifact
    CN-->>WF: state["decision"] = {pass: bool, ...}
    WF->>CD: CEL: state.decision.pass
    CD-->>WF: branch -> end
```

### 6.3 API & tool-action surface (new / changed)

**New REST endpoints** (all behind existing auth — decoded-JWT `sub` or `api_key`→agent owner — with
per-user authz; storage-agnostic via `BaseStorage`):
- `GET  /api/artifacts?conversation_id=&workflow_run_id=` → list (metadata + `current_version`, no bytes).
- `GET  /api/artifacts/<id>` → artifact + version list (+ `spec` of current version).
- `GET  /api/artifacts/<id>/versions/<n>` → one version's metadata + spec.
- `GET  /api/artifacts/<id>/download?version=` → bytes; `Content-Disposition: attachment`; **302 to an
  S3 presigned URL when `URL_STRATEGY=s3`** (add `generate_presigned_url` to `S3Storage`), else proxy
  via `get_file`.
- `POST /api/artifacts/<id>/restore` `{version}` → append the chosen version's content as a new version
  (keeps history append-only) or move the `current_version` pointer.

**Changed:** generalize `GET /api/tools/artifact/<id>` (`tools/routes.py:850`) — add an
`artifact_type:"document"|"file"` branch backed by `ArtifactsRepository` (existing notes/todo branches
unchanged).

**Tool action schemas** (the artifact/code-executor tool — actions auto-exposed to the LLM via
`get_actions_metadata`):
- `create_artifact { kind, title?, spec }` → render → store v1 → returns `{artifact_id, version, mime, size}`.
- `edit_artifact { id, instruction }` (LLM mutates the spec) or `{ id, spec_patch }` (JSON-merge) →
  re-render → append version. *Preferred for small changes (the Vercel/Canvas "targeted edit" lesson).*
- `rewrite_artifact { id, spec }` → full replacement → append version.
- `run_code { code, language?, libraries?, inputs?:[artifact_id], timeout?, capture_artifacts? }` →
  `{status, stdout_tail, structured, artifacts:[{artifact_id, mime, size}]}`. Raw executor for
  workflows/compliance; `require_approval` configurable per agent.

---

## 7. Gaps to close (prioritized)

1. **No `artifacts` table** → C1 (foundation for everything).
2. **No auth'd, storage-agnostic download endpoint; no signed URLs; no streaming reads** → C3.
3. **`/api/tools/artifact/<id>` hardcoded to notes/todos** → C3 (generalize).
4. **No code executor / sandbox** → C2.
5. **Workflow engine is linear** — no fan-out/join, so "N sub-agents in parallel then combine" isn't
   expressible (`workflow_engine.py:148`); `parallel_workers` is dead config. Needed for use case 2.
6. **No shared sub-agent workspace** — sub-agents pass only text/JSON (`node_agent.py`). The
   `sessionId`-bound sandbox + artifact references is the proposed remedy.
7. **No harness-level timeout/resource caps; no incremental tool-output streaming** → C2.
8. **MCP**: STDIO disabled, SSRF blocks internal hosts, no MCP→artifact bridge → relevant only if a
   remote sandbox is exposed via MCP.

---

## 8. Suggested phased roadmap

- **Phase 0 — Artifact foundation (no sandbox yet).** `artifacts` + `artifact_versions` tables +
  alembic migration + `ArtifactsRepository`; generalize the artifact-fetch endpoint; add the
  authenticated download endpoint + S3 presigned URLs; extend `ArtifactSidebar` with versions +
  download. *De-risks everything; useful even before code execution (e.g. server-rendered docs).*
- **Phase 1 — Code executor (chat, use case 1).** `CodeSandbox` abstraction + `SandboxManager`
  wrapping **`llm-sandbox` (MIT)** under a gVisor runtime; `code_executor` tool with approval gating +
  own timeout; store-a-spec rendering for pptx/docx/xlsx/pdf; the three-verb edit model. *Ships use
  case 1.*
- **Phase 2 — Workflow integration (use case 2).** `artifacts.*` templating namespace; pass-by-
  reference convention in `state`; `code` workflow node bound to the run session; Docling extraction
  + schema-validated decision outputs.
- **Phase 3 — Hardening & scale.** Fan-out/join workflow nodes (real parallel sub-agents); MCP
  Resources exposure; sandbox pause/resume; warm-pool tuning, idle reaping, retention/TTL +
  quotas (none exist today beyond `STT_MAX_FILE_SIZE_MB`).

---

## 9. Library & license guidance (DocsGPT is MIT)

- **Generate:** python-pptx / python-docx / openpyxl (MIT); XlsxWriter / WeasyPrint / ReportLab /
  pandas (BSD); matplotlib. **Avoid PyMuPDF (AGPL); Pandoc only as a subprocess (GPL).**
- **Sandbox:** **`llm-sandbox` (MIT) — chosen default**, run under gVisor (Apache-2.0); E2B /
  Firecracker / microsandbox (Apache-2.0) and Jupyter Kernel Gateway (BSD) as alternatives.
  **Avoid embedding Daytona / open-interpreter (AGPL).**
- **Extract:** Docling (MIT). **Open WebUI is now source-available (not MIT) — clean-room only.**

---

## 10. Decisions & remaining questions

**Resolved:**
1. **Sandbox backend default — DECIDED: wrap `llm-sandbox` (MIT)** behind the `CodeSandbox`
   abstraction, run under a **gVisor `runsc` runtime** for multi-tenant isolation, with **E2B
   (Apache-2.0)** kept as a pluggable "Firecracker-grade" backend. (See Component 2.)
2. **Session scope — recommended: bind to `conversation_id` (chat) / `workflow_run_id` (workflow).**
   A standalone, reusable "workspace" object that spans conversations is a clean Phase 3 extension
   (it just becomes another key the `SandboxManager` registry can bind to); not needed for either MVP.
3. **Persistence depth — recommended: persist-on-reap as the default.** `llm-sandbox` containers are
   cheap and pool-managed, so on idle-reap we flush workspace files to the artifact store and kill the
   kernel; on next access we spin a fresh container and re-mount artifacts by reference (LibreChat
   `codeEnvRef`/`primeFiles` pattern). True memory pause/resume (snapshot RAM+FS) is only available via
   the **E2B backend** — treat it as a per-deployment upgrade, not the default.
4. **Artifact editing — recommended: store-a-spec is the primary path** for all *generated* docs
   (deterministic, diffable versions). Add **binary round-trip editing** (lxml text-run rewrites, no
   full python-pptx re-save) as a *secondary* path for *user-uploaded* files someone wants to edit in
   place — Phase 2+, behind the same three-verb tool surface.

**Still open (team call):**
5. **Workflow parallelism (fan-out/join)** — use case 2 benefits significantly from true parallel
   sub-agents, but the engine is linear today (`workflow_engine.py:148`) and `parallel_workers` is dead
   config. Recommendation: **design the artifact-reference plumbing now so it's forward-compatible, but
   defer fan-out/join to Phase 3**; an interim *sequential* multi-document pass already works on the
   current linear engine. Confirm whether parallelism should be pulled earlier.
6. **Artifact retention / quotas** — none exist today beyond `STT_MAX_FILE_SIZE_MB`. Decide per-user
   artifact size/count caps and a TTL (LibreChat uses a 1-hour TTL on code-env files; generated
   user-facing artifacts likely want a longer or indefinite retention). Needs a product call.
7. **Preview fidelity for Office docs** — download-only card first, or invest in server-side
   `.pptx/.docx → PDF/HTML` rendering (e.g. LibreOffice headless) for inline preview? Affects scope.
