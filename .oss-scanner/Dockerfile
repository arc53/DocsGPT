# Build image for Anthropic's OSS Scanner (https://github.com/anthropics/oss-scanner).
#
# The scanner builds this file with the repository root as the context, then
# studies the result without network access. So everything the backend tests,
# the frontend tests and a running instance need is fetched here: the locked
# Python environment, the embedding models, the frontend packages, and a
# PostgreSQL and Redis to run against. See README.md next to this file.
#
# Not a deployment image; that one is docsgpt/Dockerfile.

FROM node:22-bookworm-slim@sha256:e9f565d32859f0cbfb52125eafe8be39390f24dac302dc3cdf566e8ba3ab21ee AS node
FROM ghcr.io/astral-sh/uv:0.12.17@sha256:10787c682e4184e4f290de1171fd4703dc63de99221f10fe1c99002ce7fa9acc AS uv

FROM ubuntu:24.04@sha256:73b999393d07f2bf65a40373778a44dc9a6d54ad7718d29247d8ff9413c4d6a8

# A UTF-8 locale: without one initdb creates SQL_ASCII clusters, which the
# application and the test suite's throwaway cluster cannot use.
ENV DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8

# Python 3.12 is Ubuntu 24.04's own. PostgreSQL 16 serves both the test suite
# (pytest-postgresql starts a throwaway cluster from these binaries) and a
# running instance; pgvector is there for VECTOR_STORE=pgvector.
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        python3.12 python3.12-venv ca-certificates curl git poppler-utils \
        postgresql-16 postgresql-16-pgvector redis-server && \
    rm -rf /var/lib/apt/lists/*

# Node 22 for the frontend (package.json engines) and uv for the lockfile.
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm && \
    ln -s ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx
COPY --from=uv /uv /usr/local/bin/uv

# PostgreSQL refuses to run as root and the scanner's shell is root, so the
# checkout belongs to an unprivileged user that the helper scripts switch to.
RUN useradd -m -s /bin/bash docsgpt && \
    git config --system --add safe.directory /src

# Scanner contract: the checkout lives inside the image, at /src.
COPY --chown=docsgpt:docsgpt . /src
WORKDIR /src
USER docsgpt

ENV PATH="/src/.venv/bin:/usr/lib/postgresql/16/bin:$PATH" \
    VIRTUAL_ENV=/src/.venv \
    UV_PYTHON_DOWNLOADS=never \
    UV_LINK_MODE=copy \
    HF_HUB_DISABLE_TELEMETRY=1

# The locked environment with the dev group (test tools, ruff) and docsgpt
# itself, editable. The docling extra (torch, transformers) is left out.
RUN uv sync --frozen --no-cache

# Both default embedding models and their tokenizers, into /src/models where
# the application looks for them. tiktoken's encoding ships in the package.
RUN python -m docsgpt.scripts.prefetch_models && rm -rf /src/models/.locks

# The web UI: packages for its tests, and the build the API serves from
# docsgpt/static. HUSKY=0 keeps the prepare script from installing git hooks.
RUN cd frontend && HUSKY=0 npm ci --include=dev --no-audit --no-fund && \
    cd .. && bash scripts/build_frontend.sh && \
    npm cache clean --force

# The embeddable widget's packages, for its type check and tests.
RUN cd extensions/react-widget && npm ci --no-audit --no-fund && npm cache clean --force

# From here on nothing may reach for the network: fail at once, do not retry.
ENV HF_HUB_OFFLINE=1

# A quick part of the suite, to show the image works. A failure is reported
# but does not stop the build.
RUN python -m pytest tests/security -q -p no:cacheprovider \
    || echo "WARNING: tests/security reported failures"
