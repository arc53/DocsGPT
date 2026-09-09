#!/usr/bin/env bash
# Build the web UI into docsgpt/static so the Python package ships it.
#
# The API serves that directory when it exists (docsgpt/ui.py). The package
# workflows run this before `uv build`; run it locally to test the served UI
# or to build a wheel with the UI in it.
set -euo pipefail

cd "$(dirname "$0")/../frontend"

if [ ! -d node_modules ] || [ "${CI:-}" = "true" ]; then
  npm ci --include=dev
fi

if [ -f .env.local ]; then
  echo "note: frontend/.env.local exists; its VITE_* values are baked into this build" >&2
fi

# As in frontend/Dockerfile: the committed .env.development is the baseline
# of the production build. The API rewrites VITE_API_HOST and VITE_BASE_URL
# at runtime through /config.js, so those baked values never reach a browser.
# A developer's own .env.production.local is set aside for the build and put
# back afterwards, whatever happens in between.
saved_override=""
if [ -e .env.production.local ] || [ -L .env.production.local ]; then
  saved_override="$(mktemp "${TMPDIR:-/tmp}/docsgpt-env-production-local.XXXXXX")"
  cp -p .env.production.local "$saved_override"
fi
restore_override() {
  if [ -n "$saved_override" ]; then
    mv -f "$saved_override" .env.production.local
  else
    rm -f .env.production.local
  fi
}
trap restore_override EXIT
cp .env.development .env.production.local
npm run build

# Load the runtime config ahead of the bundle, as the nginx image does.
sed -i.bak 's|<head>|<head><script src="/config.js"></script>|' dist/index.html
rm -f dist/index.html.bak
grep -q 'src="/config.js"' dist/index.html

rm -rf ../docsgpt/static
cp -R dist ../docsgpt/static
echo "built docsgpt/static ($(du -sh ../docsgpt/static | cut -f1))"
