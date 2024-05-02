# Builder Stage
FROM ubuntu:mantic as builder

# Install necessary packages
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc curl wget unzip libc6-dev python3.11 python3-pip python3-venv && \
    ln -s /usr/bin/python3.11 /usr/bin/python && \
    ln -sf /usr/bin/pip3 /usr/bin/pip

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
RUN python3 -m venv /venv
ENV PATH="/venv/bin:$PATH"

# Install Python packages
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir tiktoken && \
    pip install --no-cache-dir -r requirements.txt

# Final Stage
FROM ubuntu:mantic as final

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