#!/bin/sh
# Expose the container's VITE_* environment to the static bundle.
#
# nginx's entrypoint runs everything in /docker-entrypoint.d before serving.
# The generated /config.js is loaded by index.html ahead of the app bundle and
# read by src/env.ts, so VITE_API_HOST and friends can differ per deployment
# without rebuilding the image.
set -eu

out=/usr/share/nginx/html/config.js
{
  printf 'window.__DOCSGPT_ENV__ = {'
  first=1
  env | grep -E '^VITE_[A-Za-z0-9_]+=.' | while IFS='=' read -r key value; do
    # Empty values are skipped above (=.) so a compose passthrough like
    # ${VITE_X:-} leaves the build-time default in place.
    # JSON-escape backslashes and double quotes; values are plain URLs/ids.
    escaped=$(printf '%s' "$value" | sed 's/\\/\\\\/g; s/"/\\"/g')
    if [ "$first" -eq 1 ]; then first=0; else printf ','; fi
    printf '"%s":"%s"' "$key" "$escaped"
  done
  printf '};\n'
} > "$out"

echo "runtime-env: wrote $(grep -o 'VITE_[A-Za-z0-9_]*' "$out" | wc -l | tr -d ' ') VITE_* values to /config.js"
