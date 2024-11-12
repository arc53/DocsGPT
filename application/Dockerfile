# Builder Stage
FROM ubuntu:24.04 as builder

# Set environment variables and non-interactive mode
ENV DEBIAN_FRONTEND=noninteractive \
    PATH="/venv/bin:$PATH" \
    PYTHON_VERSION=3.11 \
    MODEL_URL="https://d3dg1063dc54p9.cloudfront.net/models/embeddings/mpnet-base-v2.zip"

# Install necessary dependencies and set up Python
RUN apt-get update && \
    apt-get install -y --no-install-recommends software-properties-common && \
    add-apt-repository ppa:deadsnakes/ppa && \
    apt-get update && \
    apt-get install -y --no-install-recommends gcc wget unzip libc6-dev python3.11 python3.11-distutils python3.11-venv && \
    rm -rf /var/lib/apt/lists/*

# Set up Python symlink in one step to minimize layers
RUN ln -s /usr/bin/python3.11 /usr/bin/python

# Download and unzip the model in a single layer, then clean up to save space
RUN wget -q $MODEL_URL -O model.zip && \
    unzip model.zip -d model && \
    rm model.zip

# Install Rust for building dependencies that require it
RUN wget -q -O - https://sh.rustup.rs | sh -s -- -y

# Copy requirements file early to leverage Docker caching of dependencies
COPY requirements.txt .

# Setup Python virtual environment and install Python packages in a single layer
RUN python3.11 -m venv /venv && \
    /venv/bin/pip install --no-cache-dir --upgrade pip && \
    /venv/bin/pip install --no-cache-dir tiktoken && \
    /venv/bin/pip install --no-cache-dir -r requirements.txt


# Final Stage
FROM ubuntu:24.04 as final

# Environment and path setup for final stage
ENV DEBIAN_FRONTEND=noninteractive \
    FLASK_APP=app.py \
    FLASK_DEBUG=true \
    PATH="/venv/bin:$PATH" \
    PYTHON_VERSION=3.11

# Install Python runtime and link it in one command to reduce layers
RUN apt-get update && \
    apt-get install -y --no-install-recommends software-properties-common && \
    add-apt-repository ppa:deadsnakes/ppa && \
    apt-get update && \
    apt-get install -y --no-install-recommends python3.11 && \
    ln -s /usr/bin/python3.11 /usr/bin/python && \
    rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Create a non-root user for running the app and set permissions
RUN groupadd -r appuser && \
    useradd -r -g appuser -d /app -s /sbin/nologin -c "Docker image user" appuser && \
    mkdir -p /app/application/inputs/local && \
    chown -R appuser:appuser /app

# Copy the virtual environment and model from the builder stage
COPY --from=builder /venv /venv
COPY --from=builder /model /app/model

# Copy application code into the image
COPY . /app/application

# Set ownership of the /app directory to appuser
RUN chown -R appuser:appuser /app

# Expose the application port
EXPOSE 7091

# Switch to non-root user
USER appuser

# Start the application with Gunicorn
CMD ["gunicorn", "-w", "2", "--timeout", "120", "--bind", "0.0.0.0:7091", "application.wsgi:app"]
