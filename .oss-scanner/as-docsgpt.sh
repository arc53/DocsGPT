#!/usr/bin/env bash
# Run a command as the docsgpt user, who owns /src. PostgreSQL will not start
# as root, so the test suite and the services need this when the shell is root:
#   .oss-scanner/as-docsgpt.sh python -m pytest tests/security
set -euo pipefail
if [ "$(id -u)" = 0 ]; then
  exec runuser -u docsgpt -- env HOME=/home/docsgpt "$@"
fi
exec "$@"
