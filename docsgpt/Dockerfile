# DocsGPT backend image.
#
# Build args:
#   EXTRAS              comma-separated optional extras to bake in, matching the
#                       pyproject extras / requirements-<extra>.txt files:
#                       docling (layout-model parser + OCR backend), milvus.
#   INSTALL_DOCLING     legacy alias for EXTRAS=docling (setup.sh writes it).
#   INSTALL_TESSERACT   bake the tesseract binary for OCR_ENGINE=tesseract.
#   EMBEDDINGS_PREFETCH registry names of the embedding models to bake; empty
#                       bakes both defaults (mpnet for upgrades, granite for
#                       new installs).
#
# Everything the default configuration needs is inside the image: embedding
# models, their tokenizers, tiktoken's encoding and, with the docling extra,
# docling's layout/table/OCR models. `python -m docsgpt.scripts.verify_offline`
# under `docker run --network none` proves it.

FROM ubuntu:24.04 AS builder

ENV DEBIAN_FRONTEND=noninteractive

# Ubuntu 24.04 ships Python 3.12 in its main archive: no PPA needed. Every pin
# resolves to a wheel, so no compiler toolchain either.
RUN apt-get update && \
    apt-get install -y --no-install-recommends python3.12 python3.12-venv ca-certificates && \
    rm -rf /var/lib/apt/lists/*

# Build context is the repository root (see .dockerignore there):
#   docker build -f docsgpt/Dockerfile .
COPY docsgpt/requirements.txt docsgpt/requirements-docling.txt docsgpt/requirements-milvus.txt ./

RUN python3.12 -m venv /venv
ENV PATH="/venv/bin:$PATH"

RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir --only-binary=:all: -r requirements.txt

# Optional extras. Each requirements-<extra>.txt is exported from the same
# lock as requirements.txt, so installing it on top only adds the extra's
# packages. The docling file takes torch from the CPU-only PyTorch index.
# Not wheels-only: docling's antlr4 runtime ships as a pure-Python sdist.
ARG EXTRAS=""
ARG INSTALL_DOCLING=false
RUN set -e; \
    extras="$EXTRAS"; \
    if [ "$INSTALL_DOCLING" = "true" ]; then extras="$extras,docling"; fi; \
    for extra in $(echo "$extras" | tr ',' ' '); do \
        echo "Installing extra: $extra"; \
        pip install --no-cache-dir -r "requirements-$extra.txt"; \
    done

# google-api-python-client bundles discovery documents for ~600 Google APIs
# (99 MB). The application builds one client, Drive v3; keep only its document.
# Building another API's client needs its file back, or static_discovery=False.
RUN find /venv/lib/python3.12/site-packages/googleapiclient/discovery_cache/documents \
        -type f ! -name 'drive.v3.json' -delete


FROM ubuntu:24.04 AS final

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && \
    apt-get install -y --no-install-recommends python3.12 poppler-utils ca-certificates && \
    ln -s /usr/bin/python3.12 /usr/bin/python && \
    rm -rf /var/lib/apt/lists/*

# opencv (rapidocr, part of the docling extra) needs libGL at import time.
ARG EXTRAS=""
ARG INSTALL_DOCLING=false
RUN if [ "$INSTALL_DOCLING" = "true" ] || echo ",$EXTRAS," | grep -q ",docling,"; then \
        apt-get update && \
        apt-get install -y --no-install-recommends libgl1 libglib2.0-0 && \
        rm -rf /var/lib/apt/lists/*; \
    fi

# Optional tesseract OCR engine (OCR_ENABLED=true with OCR_ENGINE=tesseract,
# the default engine); ~35 MB of system packages. Extra language packs are a
# deployment concern (apt: tesseract-ocr-<lang>, then list them in OCR_LANGS).
# A DeepSeek-OCR endpoint (OCR_ENGINE=deepseek) needs none of this.
ARG INSTALL_TESSERACT=false
RUN if [ "$INSTALL_TESSERACT" = "true" ]; then \
        apt-get update && \
        apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng && \
        rm -rf /var/lib/apt/lists/*; \
    fi

LABEL org.opencontainers.image.source="https://github.com/arc53/DocsGPT" \
      org.opencontainers.image.title="DocsGPT" \
      org.opencontainers.image.description="DocsGPT backend: API and Celery worker" \
      org.opencontainers.image.licenses="MIT"

WORKDIR /app

# The process user owns /app so the model prefetch below can run as it: an
# unprivileged prefetch writes the model files with the right owner up front,
# instead of a trailing chown -R that rewrites every model file into a second
# layer.
RUN groupadd -r appuser && \
    useradd -r -g appuser -d /app -s /sbin/nologin -c "Docker image user" appuser && \
    chown appuser:appuser /app && \
    install -d -o appuser -g appuser /app/models /app/docsgpt

COPY --from=builder /venv /venv

# Every cache the application reads at run time lives under /app/models and is
# filled at build time:
#   EMBEDDINGS_CACHE_DIR / HF_HUB_CACHE  FastEmbed models and their tokenizers
#                                        (chunking reads tokenizer.json from
#                                        the same hub-layout snapshot)
#   TIKTOKEN_CACHE_DIR                   cl100k_base for token accounting
#   DOCLING_ARTIFACTS_PATH               docling's models (docling extra only)
ENV EMBEDDINGS_CACHE_DIR=/app/models \
    HF_HUB_CACHE=/app/models \
    TIKTOKEN_CACHE_DIR=/app/models/tiktoken \
    DOCLING_ARTIFACTS_PATH=/app/models/docling \
    HF_HUB_DISABLE_TELEMETRY=1 \
    PATH="/venv/bin:$PATH"

# Only the modules the prefetch imports are copied first, so an unrelated
# source edit does not invalidate the model layer.
COPY --chown=appuser:appuser docsgpt/__init__.py /app/docsgpt/__init__.py
COPY --chown=appuser:appuser docsgpt/scripts/__init__.py docsgpt/scripts/prefetch_models.py /app/docsgpt/scripts/
COPY --chown=appuser:appuser docsgpt/vectorstore/__init__.py docsgpt/vectorstore/model_registry.py /app/docsgpt/vectorstore/

USER appuser

ARG EMBEDDINGS_PREFETCH=""
RUN PYTHONPATH=/app python -m docsgpt.scripts.prefetch_models ${EMBEDDINGS_PREFETCH} && \
    rm -rf /app/models/.locks /app/.cache

# docling downloads its layout, table-structure and OCR models on first parse;
# bake them so the docling variant is as self-contained as the default image.
RUN if python -c "import docling" 2>/dev/null; then \
        docling-tools models download --output-dir /app/models/docling layout tableformer rapidocr && \
        rm -rf /app/.cache; \
    fi

COPY --chown=appuser:appuser docsgpt /app/docsgpt
# One-release alias so `-A application.app.celery` style entry points keep working.
COPY --chown=appuser:appuser application/__init__.py /app/application/__init__.py

# Runtime data directories, owned by the process user so a named volume
# mounted on them (docker-compose-standalone.yaml) inherits that ownership
# and uploads work without running the container as root.
RUN mkdir -p /app/docsgpt/inputs/local /app/inputs /app/indexes /app/vectors

ENV FLASK_APP=app.py

# Thread caps. onnxruntime (FastEmbed) ignores OMP_NUM_THREADS and sizes its
# pool to the host's core count, which a CPU-limited container still reports;
# EMBEDDINGS_THREADS pins it the way OMP_NUM_THREADS pinned torch before.
ENV MALLOC_ARENA_MAX=2 \
    OMP_NUM_THREADS=4 \
    MKL_NUM_THREADS=4 \
    OPENBLAS_NUM_THREADS=4 \
    EMBEDDINGS_THREADS=4

EXPOSE 7091

# BoundedDrainUvicornWorker makes max_requests recycles safe with held-open SSE
# connections (see docsgpt/gunicorn_worker.py); with recycles now safe,
# --max-requests is raised (kept for memory hygiene) to cut churn.
CMD ["gunicorn", \
     "-w", "1", \
     "-k", "docsgpt.gunicorn_worker.BoundedDrainUvicornWorker", \
     "--bind", "0.0.0.0:7091", \
     "--timeout", "180", \
     "--graceful-timeout", "120", \
     "--keep-alive", "5", \
     "--worker-tmp-dir", "/dev/shm", \
     "--max-requests", "5000", \
     "--max-requests-jitter", "500", \
     "--config", "docsgpt/gunicorn_conf.py", \
     "docsgpt.asgi:asgi_app"]
