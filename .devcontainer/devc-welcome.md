# Welcome to DocsGPT Devcontainer

Welcome to the DocsGPT development environment! This guide will help you get started quickly.

## Starting Services

To run DocsGPT, you need to start three main services: the backend API, Celery (task queue and scheduler), and Vite (frontend). Here are the commands to start each service within the devcontainer:

### Vite (Frontend)

```bash
cd frontend
npm run dev -- --host
```

### Backend (ASGI)

Run the full app under uvicorn (serves `/mcp` and the async SSE reconnect
routes, and matches production):

```bash
uvicorn docsgpt.asgi:asgi_app --host 0.0.0.0 --port 7091 --reload
```

`flask --app docsgpt/app.py run --host=0.0.0.0 --port=7091` is faster but
serves only the WSGI Flask app. The ASGI-only routes return 404 under it:
`/mcp`, notifications (`GET /api/events`), chat reconnect
(`GET /api/messages/<id>/events`), the remote-device command stream and
artifact downloads. See "ASGI-only features" in
`docs/content/Deploying/Development-Environment.mdx`.

### Celery (Task Queue)

```bash
celery -A docsgpt.app.celery worker -l INFO -B -Q docsgpt,parsing,embeddings
```

`-B` embeds the beat scheduler, which fires scheduled agent runs, source syncs,
reconciliation and cleanups; `docsgpt worker` adds `-B` itself.
The `embeddings` queue serves every search query, so retrieval needs this worker.

The `parsing` queue serves document parsing (the `read_document` tool / workflow
native-file parse); without it those calls hang `DOCUMENT_PARSE_TIMEOUT` then
error. A dedicated `-Q parsing` worker can be GPU-enabled for heavier parsers.

## Github Codespaces Instructions

### 1. Make Ports Public:

Go to the "Ports" panel in Codespaces (usually located at the bottom of the VS Code window).

For both port 5173 and 7091, right-click on the port and select "Make Public".

![CleanShot 2025-02-12 at 09 46 14@2x](https://github.com/user-attachments/assets/00a34b16-a7ef-47af-9648-87a7e3008475)


 ### 2. Update VITE_API_HOST:

After making port 7091 public, copy the public URL provided by Codespaces for port 7091.

Open the file frontend/.env.development.

Find the line VITE_API_HOST=http://localhost:7091.

Replace http://localhost:7091 with the public URL you copied from Codespaces.

![CleanShot 2025-02-12 at 09 46 56@2x](https://github.com/user-attachments/assets/c472242f-1079-4cd8-bc0b-2d78db22b94c)
