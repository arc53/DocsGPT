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

# Download and unzip the model
RUN wget https://d3dg1063dc54p9.cloudfront.net/models/embeddings/mpnet-base-v2.zip && \
    unzip mpnet-base-v2.zip -d models && \
    rm mpnet-base-v2.zip

# Install Rust
RUN wget -q -O - https://sh.rustup.rs | sh -s -- -y

# Clean up to reduce container size
RUN apt-get remove --purge -y wget unzip && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

# Copy requirements manifests
COPY requirements.txt requirements-docling.txt ./

# Setup Python virtual environment
RUN python3.12 -m venv /venv

# Activate virtual environment and install Python packages
ENV PATH="/venv/bin:$PATH"

# Install Python packages
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir tiktoken && \
    pip install --no-cache-dir -r requirements.txt

# Optional docling parser engine (DOC_PARSER_ENGINE=docling, the docling OCR
# backend, read_document's structured output) — OFF by default: it pulls the
# layout/OCR model stack and adds gigabytes to the image. anydoc (in
# requirements.txt) is the default parser and needs none of it, and OCR runs
# natively on tesseract (below) without it.
ARG INSTALL_DOCLING=false
RUN if [ "$INSTALL_DOCLING" = "true" ]; then \
        pip install --no-cache-dir -r requirements-docling.txt; \
    fi

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

# OCR (OCR_ENABLED=true) runs on the system tesseract binary by default,
# with or without the docling extra, so ship it in every image (~35 MB).
# Opt out with --build-arg INSTALL_TESSERACT=false (e.g. a DeepSeek-OCR-only
# deployment). Extra language packs are a deployment concern
# (apt: tesseract-ocr-<lang>, then list them in OCR_LANGS).
ARG INSTALL_TESSERACT=true
RUN if [ "$INSTALL_TESSERACT" = "true" ]; then \
        apt-get update && \
        apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng && \
        rm -rf /var/lib/apt/lists/*; \
    fi

# Set working directory
WORKDIR /app

# Create a non-root user: `appuser` (Feel free to choose a name)
RUN groupadd -r appuser && \
    useradd -r -g appuser -d /app -s /sbin/nologin -c "Docker image user" appuser

# Copy the virtual environment and model from the builder stage
COPY --from=builder /venv /venv

COPY --from=builder /models /app/models

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
