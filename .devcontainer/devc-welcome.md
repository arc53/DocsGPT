# Welcome to DocsGPT Devcontainer

Welcome to the DocsGPT development environment! This guide will help you get started quickly.

## Starting Services

To run DocsGPT, you need to start three main services: Flask (backend), Celery (task queue), and Vite (frontend). Here are the commands to start each service within the devcontainer:

### Vite (Frontend)

```bash
cd frontend
npm run dev -- --host
```

### Flask (Backend)

```bash
flask --app application/app.py run --host=0.0.0.0 --port=7091
```

### Celery (Task Queue)

```bash
celery -A application.app.celery worker -l INFO
```
