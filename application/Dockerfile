# Builder Stage
FROM ubuntu:24.04 as builder

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && \
    apt-get install -y software-properties-common && \
    add-apt-repository ppa:deadsnakes/ppa && \
    apt-get update && \
    apt-get install -y --no-install-recommends gcc g++ wget unzip libc6-dev python3.12 python3.12-venv python3.12-dev && \
    rm -rf /var/lib/apt/lists/*

# Verify Python installation and setup symlink
RUN if [ -f /usr/bin/python3.12 ]; then \
        ln -s /usr/bin/python3.12 /usr/bin/python; \
    else \
        echo "Python 3.12 not found"; exit 1; \
    fi

# Install Rust
RUN wget -q -O - https://sh.rustup.rs | sh -s -- -y

# Clean up to reduce container size
RUN apt-get remove --purge -y wget unzip && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

# Copy requirements.txt
COPY requirements.txt .

# Setup Python virtual environment
RUN python3.12 -m venv /venv

# Activate virtual environment and install Python packages
ENV PATH="/venv/bin:$PATH"

# Install Python packages
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir tiktoken && \
    pip install --no-cache-dir -r requirements.txt


# Final Stage
FROM ubuntu:24.04 as final

RUN apt-get update && \
    apt-get install -y software-properties-common && \
    add-apt-repository ppa:deadsnakes/ppa && \
    apt-get update && apt-get install -y --no-install-recommends \
        python3.12 \
        libgl1 \
        libglib2.0-0 \
        poppler-utils \
        && \
    ln -s /usr/bin/python3.12 /usr/bin/python && \
    rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Create a non-root user: `appuser` (Feel free to choose a name)
RUN groupadd -r appuser && \
    useradd -r -g appuser -d /app -s /sbin/nologin -c "Docker image user" appuser

# Copy the virtual environment and model from the builder stage
COPY --from=builder /venv /venv

# Pre-fetch the embedding models into FastEmbed's cache so a fresh container
# does not download on first ingest and an air-gapped install works at all.
# Both defaults are baked: an upgraded deployment keeps using mpnet until it
# runs the re-embed script, while a new one starts on granite.
# The prefetch writes hub-layout snapshots (including tokenizer.json) here, so
# HF_HUB_CACHE has to point at the same directory: chunking loads the tokenizer
# through ``tokenizers``, which reads the hub cache and would otherwise fetch
# over the network on first ingest -- and fall back to cl100k when offline.
ENV EMBEDDINGS_CACHE_DIR=/app/models \
    HF_HUB_CACHE=/app/models

# Only the modules the prefetch imports are copied first. It reaches nothing
# beyond model_registry, which is stdlib-only, so keeping the full source copy
# below this layer stops an unrelated edit from re-downloading ~780 MB of model
# artifacts on every build.
COPY __init__.py /app/application/__init__.py
COPY scripts/__init__.py scripts/prefetch_models.py /app/application/scripts/
COPY vectorstore/__init__.py vectorstore/model_registry.py /app/application/vectorstore/
ARG EMBEDDINGS_PREFETCH=""
RUN PYTHONPATH=/app /venv/bin/python -m application.scripts.prefetch_models ${EMBEDDINGS_PREFETCH}

# Copy your application code
COPY . /app/application

# Change the ownership of the /app directory to the appuser

RUN mkdir -p /app/application/inputs/local
RUN chown -R appuser:appuser /app

# Set environment variables
ENV FLASK_APP=app.py \
    FLASK_DEBUG=true \
    PATH="/venv/bin:$PATH"

ENV MALLOC_ARENA_MAX=2 \
    OMP_NUM_THREADS=4 \
    MKL_NUM_THREADS=4 \
    OPENBLAS_NUM_THREADS=4

# Expose the port the app runs on
EXPOSE 7091

# Switch to non-root user
USER appuser

# BoundedDrainUvicornWorker makes max_requests recycles safe with held-open SSE
# connections (see application/gunicorn_worker.py); with recycles now safe,
# --max-requests is raised (kept for memory hygiene) to cut churn.
CMD ["gunicorn", \
     "-w", "1", \
     "-k", "application.gunicorn_worker.BoundedDrainUvicornWorker", \
     "--bind", "0.0.0.0:7091", \
     "--timeout", "180", \
     "--graceful-timeout", "120", \
     "--keep-alive", "5", \
     "--worker-tmp-dir", "/dev/shm", \
     "--max-requests", "5000", \
     "--max-requests-jitter", "500", \
     "--config", "application/gunicorn_conf.py", \
     "application.asgi:asgi_app"]
