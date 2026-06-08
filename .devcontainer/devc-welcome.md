# Welcome to DocsGPT Devcontainer

Welcome to the DocsGPT development environment! This guide will help you get started quickly.

## Starting Services

To run DocsGPT, you need to start three main services: Flask (backend), Celery (task queue), and Vite (frontend). Here are the commands to start each service within the devcontainer:

### Vite (Frontend)

```bash
cd frontend
npm run dev -- --host
```

### Backend (ASGI)

Run the full app under uvicorn (serves `/mcp` and the async SSE reconnect
routes, and matches production):

```bash
uvicorn application.asgi:asgi_app --host 0.0.0.0 --port 7091 --reload
```

`flask --app application/app.py run --host=0.0.0.0 --port=7091` is faster but
serves only the WSGI Flask app — it omits `/mcp` and the reconnect reader
`GET /api/messages/<id>/events`, so a dropped stream won't auto-resume.

### Celery (Task Queue)

```bash
celery -A application.app.celery worker -l INFO
```

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
