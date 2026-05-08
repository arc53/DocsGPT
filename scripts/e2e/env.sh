#!/usr/bin/env bash
# scripts/e2e/env.sh
#
# Environment variables for the DocsGPT end-to-end test stack.
# This file is intentionally passive: it exports variables and nothing else.
# It is `source`d by scripts/e2e/up.sh (and potentially by developers who want
# to run Flask/Celery manually against the e2e stack).
#
# Mirrors `Appendix A — .env.e2e reference` in e2e-plan.md. If you add/remove
# a variable here, update the plan doc as well.
#
# DO NOT run commands (mkdir, touch, etc.) from this file — keep it pure.

# -----------------------------------------------------------------------------
# Postgres
# -----------------------------------------------------------------------------
export POSTGRES_URI="postgresql://docsgpt:docsgpt@127.0.0.1:5432/docsgpt_e2e"

# -----------------------------------------------------------------------------
# Redis (dev uses DBs 0/1/2; e2e uses 11/12/13 to stay isolated)
# -----------------------------------------------------------------------------
export CELERY_BROKER_URL="redis://127.0.0.1:6379/11"
export CELERY_RESULT_BACKEND="redis://127.0.0.1:6379/12"
export CACHE_REDIS_URL="redis://127.0.0.1:6379/13"

# -----------------------------------------------------------------------------
# Mongo — unused in the e2e stack (app fully cut over on this branch)
# -----------------------------------------------------------------------------
export MONGO_URI=""

# -----------------------------------------------------------------------------
# Vector + storage
# -----------------------------------------------------------------------------
export VECTOR_STORE="faiss"
export EMBEDDINGS_NAME="huggingface_sentence-transformers/all-mpnet-base-v2"
export STORAGE_TYPE="local"
export URL_STRATEGY="backend"
export UPLOAD_FOLDER=".e2e-tmp/inputs"

# -----------------------------------------------------------------------------
# Flask
# -----------------------------------------------------------------------------
export API_URL="http://127.0.0.1:7099"
export FLASK_DEBUG_MODE="false"

# -----------------------------------------------------------------------------
# Auth (specs can override AUTH_TYPE per-launch via process env)
# -----------------------------------------------------------------------------
export AUTH_TYPE="session_jwt"
export JWT_SECRET_KEY="e2e-fixed-secret-never-use-in-prod"
export ENCRYPTION_SECRET_KEY="e2e-fixed-encryption-key-never-use-in-prod"

# -----------------------------------------------------------------------------
# LLM → mock stub on 127.0.0.1:7899
# -----------------------------------------------------------------------------
export LLM_PROVIDER="openai"
export LLM_NAME="gpt-4o-mini"
export API_KEY="e2e-fake-key"
export OPENAI_API_KEY="e2e-fake-key"
export OPENAI_BASE_URL="http://127.0.0.1:7899/v1"
export EMBEDDINGS_BASE_URL="http://127.0.0.1:7899/v1"
export EMBEDDINGS_KEY="e2e-fake-key"

# -----------------------------------------------------------------------------
# Determinism — disable features that introduce non-determinism in tests
# -----------------------------------------------------------------------------
export ENABLE_CONVERSATION_COMPRESSION="false"
export ENABLE_TOOL_PREFETCH="false"
export PARSE_PDF_AS_IMAGE="false"
export DOCLING_OCR_ENABLED="false"
