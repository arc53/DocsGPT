# AGENTS.md

- Read `CONTRIBUTING.md` before making non-trivial changes.
- For day-to-day development and feature work, follow the development-environment workflow rather than defaulting to `setup.sh` / `setup.ps1`.
- Avoid using the setup scripts during normal feature work unless the user explicitly asks for them. Users configure `.env` usually.
- Try to follow red/green TDD

### Check existing dev prerequisites first

For feature work, do **not** assume the environment needs to be recreated.

- Check whether the user already has a Python virtual environment such as `venv/` or `.venv/`.
- Check whether MongoDB is already running.
- Check whether Redis is already running.
- Reuse what is already working. Do not stop or recreate MongoDB, Redis, or the Python environment unless the task is environment setup or troubleshooting.

## Normal local development commands

Use these commands once the dev prerequisites above are satisfied.

### Backend

```bash
source .venv/bin/activate  # macOS/Linux
uv pip install -r application/requirements.txt  # or: pip install -r application/requirements.txt
```

Run the Flask API (if needed):

```bash
flask --app application/app.py run --host=0.0.0.0 --port=7091
```

Run the Celery worker in a separate terminal (if needed):

```bash
celery -A application.app.celery worker -l INFO
```

On macOS, prefer the solo pool for Celery:

```bash
python -m celery -A application.app.celery worker -l INFO --pool=solo
```

### Frontend

Install dependencies only when needed, then run the dev server:

```bash
cd frontend
npm install --include=dev
npm run dev
```

### Docs site

```bash
cd docs
npm install
```

### Python / backend changes validation

```bash
ruff check .
python -m pytest
```

### Frontend changes

```bash
cd frontend && npm run lint
cd frontend && npm run build
```

### Documentation changes

```bash
cd docs && npm run build
```

If Vale is installed locally and you edited prose, also run:

```bash
vale .
```

## Repository map

- `application/`: Flask backend, API routes, agent logic, retrieval, parsing, security, storage, Celery worker, and WSGI entrypoints.
- `tests/`: backend unit/integration tests and test-only Python dependencies.
- `frontend/`: Vite + React + TypeScript application.
- `frontend/src/`: main UI code, including `components`, `conversation`, `hooks`, `locale`, `settings`, `upload`, and Redux store wiring in `store.ts`.
- `docs/`: separate documentation site built with Next.js/Nextra.
- `extensions/`: integrations and widgets such as Chatwoot, Chrome, Discord, React widget, Slack bot, and web widget.
- `deployment/`: Docker Compose variants and Kubernetes manifests.

## Coding rules

### Backend

- Follow PEP 8 and keep Python line length at or under 120 characters.
- Use type hints for function arguments and return values.
- Add Google-style docstrings to new or substantially changed functions and classes.
- Add or update tests under `tests/` for backend behavior changes.
- Keep changes narrow in `api`, `auth`, `security`, `parser`, `retriever`, and `storage` areas.

### Backend Abstractions

- LLM providers implement a common interface in `application/llm/` (add new providers by extending the base class).
- Vector stores are abstracted in `application/vectorstore/`.
- Parsers live in `application/parser/` and handle different document formats in the ingestion stage.
- Agents and tools are in `application/agents/` and `application/agents/tools/`.
- Celery setup/config lives in `application/celery_init.py` and `application/celeryconfig.py`.
- Settings and env vars are managed via Pydantic in `application/core/settings.py`.

### Frontend

- Follow the existing ESLint + Prettier setup.
- Prefer small, reusable functional components and hooks.
- If shared state must be added, use Redux rather than introducing a new global state library.
- Avoid broad UI refactors unless the task explicitly asks for them.
- Do not re-create components if we already have some in the app.

## PR readiness

Before opening a PR:

- run the relevant validation commands above
- confirm backend changes still work end-to-end after ingesting sample data when applicable
- clearly summarize user-visible behavior changes
- mention any config, dependency, or deployment implications
- Ask your user to attach a screenshot or a video to it