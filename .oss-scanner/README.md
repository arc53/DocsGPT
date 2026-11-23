# OSS Scanner files

DocsGPT is enrolled in Anthropic's [OSS Scanner](https://github.com/anthropics/oss-scanner), which builds the
project in an isolated machine, studies it without network access and mails what it finds to `security@arc53.com`.
The enrolment itself (`projects/docsgpt/project.yaml`) lives in the scanner's repository and points at these files:

| File | Purpose |
|---|---|
| `Dockerfile` | Builds the image the scanner works in. Not a deployment image. |
| `Dockerfile.dockerignore` | Makes that build see the whole checkout, not the root `.dockerignore` selection. |
| `report_guidelines.md` | How we would like reports written. |
| `patch_guidelines.md` | How we would like proposed patches made. |
| `services.sh`, `as-docsgpt.sh` | Helpers for working inside the image. |

The threat model the scanner reads is [`.github/THREAT_MODEL.md`](../.github/THREAT_MODEL.md).

## Inside the image

The checkout is at `/src` and belongs to the `docsgpt` user. The Python environment is `/src/.venv` (on `PATH`), the
embedding models are in `/src/models`, the web UI is built into `/src/docsgpt/static`, and `frontend/` and
`extensions/react-widget/` have their packages installed. There is no network, and none is needed.

PostgreSQL does not start as root, so run the backend tests and the services as `docsgpt`:

```bash
.oss-scanner/as-docsgpt.sh python -m pytest tests/security      # one directory
.oss-scanner/as-docsgpt.sh python -m pytest -n 2                # the whole suite
cd frontend && npm test                                          # frontend unit tests
```

Two groups of backend tests do not pass in this image, and neither points at a fault in the application:

- About a dozen tests (`tests/api/user/test_tools_mcp_pg.py`, one in `tests/guardrails/`) resolve `example.com` and
  fail without a network.
- The image has the pgvector extension, so the "live" pgvector and graph tests run here (CI has no pgvector and
  skips them). They commit to the shared test database and the suite's teardown guard reports each as an error.

To run an instance, start PostgreSQL and Redis, then the API, the worker and a mock model provider:

```bash
.oss-scanner/services.sh
.oss-scanner/as-docsgpt.sh docsgpt dev --mock-llm               # API and UI on http://127.0.0.1:7091
```

`AGENTS.md` at the repository root describes the layout of the code and the other commands.

## Checking a change to these files

From a checkout of `anthropics/oss-scanner`, `tools/check docsgpt` builds the image the way the scanner does and
opens a shell in it with the network off.
