# Stage 1: Builder stage for Tiktoken
FROM python:3.10-slim-bullseye as builder

# Install required dependencies for building
RUN apt-get update && apt-get install -y gcc curl

# Install Rust toolchain
RUN curl https://sh.rustup.rs -sSf | sh -s -- -y && apt-get install --reinstall libc6-dev -y
ENV PATH="/root/.cargo/bin:${PATH}"

# Install Tiktoken
RUN pip install --upgrade pip && pip install tiktoken==0.3.3

# Copy requirements.txt for application
COPY requirements.txt .

# Install other Python dependencies
RUN pip install -r requirements.txt

# Stage 2: Final image
FROM python:3.10-slim-bullseye

# Copy pre-built packages and binaries from builder stage
COPY --from=builder /usr/local/ /usr/local/

# Set working directory
WORKDIR /app

# Copy application code
COPY . /app/application

# Set environment variables for Flask
ENV FLASK_APP=app.py
ENV FLASK_DEBUG=true

# Expose port
EXPOSE 7091

# Define the command to run the application
CMD ["gunicorn", "-w", "2", "--timeout", "120", "--bind", "0.0.0.0:7091", "application.wsgi:app"]
