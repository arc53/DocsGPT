FROM python:3.10-slim-bullseye as builder

# Tiktoken requires Rust toolchain, so build it in a separate stage
RUN apt-get update && apt-get install -y gcc curl
RUN curl https://sh.rustup.rs -sSf | sh -s -- -y && apt-get install --reinstall libc6-dev -y
ENV PATH="/root/.cargo/bin:${PATH}"
RUN pip install --upgrade pip && pip install tiktoken==0.3.3
COPY requirements.txt .
RUN pip install -r requirements.txt

FROM python:3.10-slim-bullseye

# Copy pre-built packages and binaries from builder stage
COPY --from=builder /usr/local/ /usr/local/

WORKDIR /app
COPY . /app
ENV FLASK_APP=app.py
ENV FLASK_DEBUG=true

EXPOSE 5001

CMD ["gunicorn", "-w", "2", "--timeout", "120", "--bind", "0.0.0.0:5001", "wsgi:app"]
