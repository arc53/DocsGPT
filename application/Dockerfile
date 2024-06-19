# Builder Stage
FROM ubuntu:24.04 as builder

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && \
    apt-get install -y software-properties-common

RUN add-apt-repository ppa:deadsnakes/ppa

# Install necessary packages and Python
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc curl wget unzip libc6-dev python3.11 python3.11-distutils python3.11-venv && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/* 

# Verify Python installation and setup symlink
RUN if [ -f /usr/bin/python3.11 ]; then \
        ln -s /usr/bin/python3.11 /usr/bin/python; \
    else \
        echo "Python 3.11 not found"; exit 1; \
    fi

# Download and unzip the model
RUN wget https://d3dg1063dc54p9.cloudfront.net/models/embeddings/mpnet-base-v2.zip && \
    unzip mpnet-base-v2.zip -d model && \
    rm mpnet-base-v2.zip

# Install Rust
RUN curl https://sh.rustup.rs -sSf | sh -s -- -y

# Clean up to reduce container size
RUN apt-get remove --purge -y wget unzip && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

# Copy requirements.txt
COPY requirements.txt .

# Setup Python virtual environment
RUN python3.11 -m venv /venv

# Activate virtual environment and install Python packages
ENV PATH="/venv/bin:$PATH"

# Install Python packages
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir tiktoken && \
    pip install --no-cache-dir -r requirements.txt

# Final Stage
FROM ubuntu:24.04 as final

RUN apt-get update && \
    apt-get install -y software-properties-common

RUN add-apt-repository ppa:deadsnakes/ppa

# Install Python
RUN apt-get update && apt-get install -y --no-install-recommends python3.11 && \
    ln -s /usr/bin/python3.11 /usr/bin/python && \
    rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Create a non-root user: `appuser` (Feel free to choose a name)
RUN groupadd -r appuser && \
    useradd -r -g appuser -d /app -s /sbin/nologin -c "Docker image user" appuser

# Copy the virtual environment and model from the builder stage
COPY --from=builder /venv /venv
COPY --from=builder /model /app/model

# Copy your application code
COPY . /app/application

# Change the ownership of the /app directory to the appuser
	
RUN mkdir -p /app/application/inputs/local
RUN chown -R appuser:appuser /app

# Set environment variables
ENV FLASK_APP=app.py \
    FLASK_DEBUG=true \
    PATH="/venv/bin:$PATH"

# Expose the port the app runs on
EXPOSE 7091

# Switch to non-root user
USER appuser

# Start Gunicorn
CMD ["gunicorn", "-w", "2", "--timeout", "120", "--bind", "0.0.0.0:7091", "application.wsgi:app"]