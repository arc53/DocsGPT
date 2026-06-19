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
export AUTH_TYPE="${AUTH_TYPE:-session_jwt}"
export JWT_SECRET_KEY="e2e-fixed-secret-never-use-in-prod"
export ENCRYPTION_SECRET_KEY="e2e-fixed-encryption-key-never-use-in-prod"

# OIDC mode (AUTH_TYPE=oidc) — points at the mock IdP that oidc.spec.ts
# spawns on demand (scripts/e2e/mock_oidc_idp.py, port 7999). Discovery is
# lazy, so Flask boots fine before the IdP is up. Every OIDC_* var is pinned
# here because the app's load_dotenv() walks up and reads the repo .env —
# whatever a developer keeps there must not leak into the e2e stack.
if [[ "${AUTH_TYPE}" == "oidc" ]]; then
    export OIDC_ISSUER="${OIDC_ISSUER:-http://127.0.0.1:7999}"
    export OIDC_CLIENT_ID="${OIDC_CLIENT_ID:-docsgpt-e2e}"
    export OIDC_FRONTEND_URL="${OIDC_FRONTEND_URL:-http://127.0.0.1:5179}"
    export OIDC_CLIENT_SECRET="${OIDC_CLIENT_SECRET:-}"
    export OIDC_SCOPES="${OIDC_SCOPES:-openid profile email}"
    export OIDC_USER_ID_CLAIM="${OIDC_USER_ID_CLAIM:-sub}"
    export OIDC_REDIRECT_URI="${OIDC_REDIRECT_URI:-}"
    export OIDC_SESSION_LIFETIME_SECONDS="${OIDC_SESSION_LIFETIME_SECONDS:-28800}"
    export OIDC_PROVIDER_NAME="${OIDC_PROVIDER_NAME:-}"
    export OIDC_ALLOWED_GROUPS="${OIDC_ALLOWED_GROUPS:-}"
    export OIDC_GROUPS_CLAIM="${OIDC_GROUPS_CLAIM:-groups}"
    export SCIM_ENABLED="${SCIM_ENABLED:-false}"
    export SCIM_TOKEN="${SCIM_TOKEN:-}"
fi

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
