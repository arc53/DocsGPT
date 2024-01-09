FROM python:3.11-slim-bullseye as builder

# Tiktoken requires Rust toolchain, so build it in a separate stage
RUN apt-get update && apt-get install -y gcc curl
RUN curl https://sh.rustup.rs -sSf | sh -s -- -y && apt-get install --reinstall libc6-dev -y
ENV PATH="/root/.cargo/bin:${PATH}"
RUN pip install --upgrade pip && pip install tiktoken==0.5.2
COPY requirements.txt .
RUN pip install -r requirements.txt
RUN apt-get install -y wget unzip
RUN wget https://docsgpt.s3.eu-west-1.amazonaws.com/models/embeddings/mpnet-base-v2.zip
RUN unzip mpnet-base-v2.zip -d model
RUN rm mpnet-base-v2.zip

FROM python:3.11-slim-bullseye

# Copy pre-built packages and binaries from builder stage
COPY --from=builder /usr/local/ /usr/local/

WORKDIR /app
COPY --from=builder /model /app/model

COPY . /app/application
ENV FLASK_APP=app.py
ENV FLASK_DEBUG=true

EXPOSE 7091

CMD ["gunicorn", "-w", "2", "--timeout", "120", "--bind", "0.0.0.0:7091", "application.wsgi:app"]
