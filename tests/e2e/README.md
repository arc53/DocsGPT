# DocsGPT E2E Tests

End-to-end tests for DocsGPT, driven by Playwright against the full native
dev stack (Flask + Celery + Vite + a mock LLM stub), backed by a disposable
`docsgpt_e2e` Postgres database.

This is an isolated Node workspace. It has its own `package.json` so
Playwright never ends up in the frontend app bundle.

## Quick start

```bash
# 1. Install JS deps (first time only).
npm install

# 2. Install the Chromium browser Playwright will drive (first time only).
npm run e2e:install

# 3. Bake the Postgres template DB (one-time, idempotent).
../../scripts/e2e/bake_template.sh

# 4. Run the whole suite: boots services, runs tests, tears down.
npm run e2e
```

## Interactive development

When iterating on a spec you want the services up across many runs:

```bash
npm run e2e:up    # boot Flask + Celery + Vite + mock LLM, leave them running
npm run e2e:ui    # open Playwright UI against the running stack
npm run e2e:down  # tear down when done
```

## Reports

After a run, view the HTML report:

```bash
npm run e2e:report
```

Traces, screenshots, and videos for failed tests land under `test-results/`.
Trace is captured `on-first-retry` (the first attempt runs clean; the retry
records for debugging).

## Structure

- `specs/` — test files, grouped by tier (`auth/`, `tier-a/`, `tier-b/`, `tier-c/`).
- `helpers/` — shared TypeScript helpers: `auth.ts`, `db.ts`, `reset.ts`,
  `api.ts`. Imported via the `@helpers/*` path alias.
- `fixtures/` — static fixture documents (PDFs, markdown, text) used by
  upload specs. Body content must be deterministic — no dates, UUIDs, or
  random tokens.

## Full plan

See [`../../e2e-plan.md`](../../e2e-plan.md) for the phased rollout,
parallelization model, and Tier-A/B/C spec inventory.
