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
# Pre-baked doc libs are all permissive (MIT/BSD/Apache) for speed/reliability;
# runtime `pip install` still works because egress is open. PyMuPDF and any
# other AGPL lib are intentionally excluded; Docling is deferred to its own slice.
#
# HARDENING (separate slice — NOT done here): run under the gVisor `runsc`
# runtime, add network-layer SSRF blocks (drop RFC1918 / link-local /
# 169.254.169.254), seccomp profile, read-only root FS + quota'd scratch dir,
# and cgroup CPU/mem/PID caps wired from SANDBOX_MEMORY / SANDBOX_CPUS.
FROM python:3.12-slim

# Non-root user for the runner (untrusted code runs as this UID).
RUN useradd --create-home --uid 10001 sandbox

# Exact pins for reproducible builds and no license drift (all MIT/BSD/Apache).
RUN pip install --no-cache-dir \
    jupyter-kernel-gateway==3.0.1 \
    ipykernel==6.29.5 \
    python-pptx==1.0.2 \
    python-docx==1.1.2 \
    openpyxl==3.1.5 \
    reportlab==4.2.5 \
    pandas==2.2.3 \
    matplotlib==3.9.2

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
COPY kernel-launch.sh /opt/docsgpt/kernel-launch.sh
RUN chmod 0555 /opt/docsgpt/kernel-launch.sh
COPY gateway-launch.sh /opt/docsgpt/gateway-launch.sh
RUN chmod 0555 /opt/docsgpt/gateway-launch.sh
COPY kernels/docsgpt-python/kernel.json /usr/local/share/jupyter/kernels/docsgpt-python/kernel.json

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
