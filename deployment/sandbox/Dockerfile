# docsgpt-sandbox: the always-on code-execution runner.
#
# One container runs a Jupyter Kernel Gateway; each sandbox session is an
# in-process kernel (a child process), NOT a child container. This image does
# NOT mount the Docker socket and never spawns containers — that avoids the
# host-root risk of Docker-in-Docker and is the core security win.
#
# The app (backend/worker) is the CLIENT and reaches this service over
# HTTP + WebSocket via SANDBOX_GATEWAY_URL.
#
# CONTENTS come from docsgpt/sandbox/manifest.py, the list the Daytona snapshot
# (scripts/build_daytona_snapshot.py) builds from too. This Dockerfile installs
# from files generated from it -- requirements.txt, install-system.sh,
# sandbox.env, manifest.json; edit the manifest and run
# `python scripts/export_sandbox_manifest.py`, never these files.
#
# LICENSES. The Python libraries are permissive (MIT, BSD, Apache-2.0, HPND for
# Pillow), and so are Node.js (MIT, unpacked from the official nodejs.org
# tarball and checked against the SHA-256 pinned in the manifest), Chromium
# (BSD-3-Clause plus its bundled third-party code) and tesseract (Apache-2.0).
# LibreOffice is MPL-2.0. The fonts are under the Bitstream Vera (DejaVu) and
# SIL OFL-1.1 (Liberation, Carlito, Caladea, Noto) licenses. Two packages are
# GPL and are only ever run as separate programs, never linked into the Python
# code: poppler-utils (pdftotext, pdftoppm) and Debian's ffmpeg build (ffmpeg,
# ffprobe). They are unmodified Debian packages whose corresponding source
# Debian publishes (`apt-get source poppler ffmpeg`, or sources.debian.org);
# anyone redistributing this image passes on that GPL offer. PyMuPDF (AGPL) and
# any other AGPL library are intentionally excluded; pdfplumber, pypdf and
# pypdfium2 cover PDF reading. Runtime `pip install` still works while egress
# is open.
#
# HARDENING (separate slice — NOT done here): run under the gVisor `runsc`
# runtime, add network-layer SSRF blocks (drop RFC1918 / link-local /
# 169.254.169.254), seccomp profile, read-only root FS + quota'd scratch dir,
# and cgroup CPU/mem/PID caps wired from SANDBOX_MEMORY / SANDBOX_CPUS.
FROM python:3.12-slim

# Non-root user for the runner (untrusted code runs as this UID).
RUN useradd --create-home --uid 10001 sandbox

# System packages (OCR, poppler, ffmpeg, headless LibreOffice and Chromium,
# fonts) and the pinned Node.js build. Its own layer: it is the largest and
# changes least often.
COPY install-system.sh /opt/docsgpt/install-system.sh
RUN sh /opt/docsgpt/install-system.sh

# Python libraries, exact pins from the manifest.
COPY requirements.txt /opt/docsgpt/requirements.txt
RUN PIP_ROOT_USER_ACTION=ignore pip install --no-cache-dir -r /opt/docsgpt/requirements.txt

# Docling (MIT) — OFF by default because it pulls torch + models and makes the
# image multi-GB. NOTE: document parsing now runs on the Celery `parsing` worker
# (see read_document / parse_document_worker), NOT in this sandbox, so this
# INSTALL_DOCLING build-arg path is effectively unused for the read_document flow;
# it remains only for sandbox code that opts into Docling explicitly. The build
# mechanics are kept for that case. Docling is MIT and uses its own PDF backend;
# PyMuPDF (AGPL) is NOT installed here. The base image stays docling-free.
ARG INSTALL_DOCLING=false
RUN if [ "$INSTALL_DOCLING" = "true" ]; then \
        pip install --no-cache-dir docling==2.8.3; \
    fi

# Env-scrubbing kernel launcher + custom kernelspec. The launcher re-execs
# ipykernel under a minimal allowlisted env (env -i) so NO secret in the
# gateway's environment (*_API_KEY, *_TOKEN, POSTGRES_URI, the gateway auth
# token, ...) ever reaches kernel code. The kernelspec ships under a DISTINCT
# name ("docsgpt-python"), so the app selects it with SANDBOX_KERNEL_NAME and it
# is never shadowed by the stock ipykernel "python3" spec regardless of the
# python prefix. The stock "python3" spec is left untouched (no overwrite, no
# kernelspec-name precedence to rely on). SECURITY: never give this image
# `env_file: ../.env` -- the scrubber blocks exfil from the kernel, but the
# runner image itself should stay free of app secrets it has no use for.
#
# kernel-env.sh does the scrubbing and gives kernels a writable HOME under /tmp
# (the root FS is read-only); sandbox.env is the image environment it passes on.
# kernel-startup.py runs inside each kernel and drops the FORCE_COLOR ipykernel sets.
COPY kernel-env.sh /opt/docsgpt/kernel-env.sh
COPY kernel-launch.sh /opt/docsgpt/kernel-launch.sh
COPY kernel-startup.py /opt/docsgpt/kernel-startup.py
COPY gateway-launch.sh /opt/docsgpt/gateway-launch.sh
COPY sandbox.env /opt/docsgpt/sandbox.env
COPY kernels/docsgpt-python/kernel.json /usr/local/share/jupyter/kernels/docsgpt-python/kernel.json

# Conversion helpers on PATH (html_render.py picks its mode from the name it is
# run as), and the smoke test with the manifest it checks against:
#   docker run --rm --read-only --tmpfs /tmp IMAGE \
#     /opt/docsgpt/kernel-env.sh python /opt/docsgpt/smoke_test.py
COPY helpers/office_convert.py /usr/local/bin/office-convert
COPY helpers/html_render.py /usr/local/bin/html-to-pdf
COPY helpers/html_render.py /usr/local/bin/html-screenshot
COPY smoke_test.py /opt/docsgpt/smoke_test.py
COPY manifest.json /opt/docsgpt/manifest.json
RUN chmod 0555 /opt/docsgpt/kernel-env.sh /opt/docsgpt/kernel-launch.sh /opt/docsgpt/gateway-launch.sh \
        /usr/local/bin/office-convert /usr/local/bin/html-to-pdf /usr/local/bin/html-screenshot \
    && chmod 0444 /opt/docsgpt/sandbox.env /opt/docsgpt/kernel-startup.py /opt/docsgpt/smoke_test.py \
        /opt/docsgpt/manifest.json

# Numeric UID (not the name) so a kubelet with `runAsNonRoot: true` can verify
# the user is non-root without resolving /etc/passwd. This uid MUST match
# `runAsUser` in deployment/k8s/deployments/sandbox-deploy.yaml.
USER 10001
WORKDIR /home/sandbox

EXPOSE 8888

# The launcher REQUIRES SANDBOX_GATEWAY_AUTH_TOKEN and fails closed if it is
# unset: the gateway control API is reachable from kernel code over loopback, so
# it must never run unauthenticated (see gateway-launch.sh). The token is shared
# with the app and is scrubbed from the kernel env by kernel-launch.sh.
CMD ["/opt/docsgpt/gateway-launch.sh"]
