#!/bin/sh
set -e

# Strip quotes from a string if it is quoted
strip_quotes() {
  printf '%s' "$1" | sed -e 's/^"\(.*\)"$/\1/' -e "s/^'\(.*\)'\$/\1/"
}

VITE_NOTIFICATION_TEXT=$(strip_quotes "${VITE_NOTIFICATION_TEXT:-}")
VITE_NOTIFICATION_LINK=$(strip_quotes "${VITE_NOTIFICATION_LINK:-}")
VITE_API_HOST=$(strip_quotes "${VITE_API_HOST:-}")
VITE_API_STREAMING=$(strip_quotes "${VITE_API_STREAMING:-}")
VITE_GOOGLE_CLIENT_ID=$(strip_quotes "${VITE_GOOGLE_CLIENT_ID:-}")
VITE_GOOGLE_PICKER_API_KEY=$(strip_quotes "${VITE_GOOGLE_PICKER_API_KEY:-}")
VITE_BASE_URL=$(strip_quotes "${VITE_BASE_URL:-}")

VITE_ENABLE_VOICE_INPUT=$(strip_quotes "${VITE_ENABLE_VOICE_INPUT:-}")
VITE_DISABLE_SOURCE_FE=$(strip_quotes "${VITE_DISABLE_SOURCE_FE:-}")
VITE_USE_V1_API=$(strip_quotes "${VITE_USE_V1_API:-}")
VITE_SHARE_POINT_CLIENT_ID=$(strip_quotes "${VITE_SHARE_POINT_CLIENT_ID:-}")
VITE_CONFLUENCE_CLIENT_ID=$(strip_quotes "${VITE_CONFLUENCE_CLIENT_ID:-}")

jq -n \
  --arg text "$VITE_NOTIFICATION_TEXT" \
  --arg link "$VITE_NOTIFICATION_LINK" \
  --arg apiHost "$VITE_API_HOST" \
  --arg streaming "$VITE_API_STREAMING" \
  --arg googleId "$VITE_GOOGLE_CLIENT_ID" \
  --arg googlePickerApiKey "$VITE_GOOGLE_PICKER_API_KEY" \
  --arg baseUrl "$VITE_BASE_URL" \
  --arg enableVoiceInput "$VITE_ENABLE_VOICE_INPUT" \
  --arg disableSourceFE "$VITE_DISABLE_SOURCE_FE" \
  --arg useV1Api "$VITE_USE_V1_API" \
  --arg sharePointClientId "$VITE_SHARE_POINT_CLIENT_ID" \
  --arg confluentClientId "$VITE_CONFLUENCE_CLIENT_ID" \
  '{
    VITE_NOTIFICATION_TEXT: $text,
    VITE_NOTIFICATION_LINK: $link,
    VITE_API_HOST: $apiHost,
    VITE_API_STREAMING: $streaming,
    VITE_GOOGLE_CLIENT_ID: $googleId,
    VITE_GOOGLE_PICKER_API_KEY: $googlePickerApiKey,
    VITE_BASE_URL: $baseUrl,
    VITE_ENABLE_VOICE_INPUT: $enableVoiceInput,
    VITE_DISABLE_SOURCE_FE: $disableSourceFE,
    VITE_USE_V1_API: $useV1Api,
    VITE_SHARE_POINT_CLIENT_ID: $sharePointClientId,
    VITE_CONFLUENCE_CLIENT_ID: $confluentClientId
  }' > /tmp/env.json

# adds the env variables to envConfig.js file, which index.html will load to access the env variables through window._env_ object
echo "window._env_ = $(cat /tmp/env.json);" > /usr/share/nginx/html/envConfig.js

exec "$@"