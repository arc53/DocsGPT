#!/bin/bash

set -e  # Exit immediately if a command exits with a non-zero status

if [ ! -f frontend/.env.development ]; then
  cp -n .env-template frontend/.env.development || true # Assuming .env-template is in the root
fi

# Determine VITE_API_HOST based on environment
if [ -n "$CODESPACES" ]; then
  # Running in Codespaces
  CODESPACE_NAME=$(echo "$CODESPACES" | cut -d'-' -f1) # Extract codespace name
  PUBLIC_API_HOST="https://${CODESPACE_NAME}-7091.${GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN}"
  echo "Setting VITE_API_HOST for Codespaces: $PUBLIC_API_HOST in frontend/.env.development"
  sed -i "s|VITE_API_HOST=.*|VITE_API_HOST=$PUBLIC_API_HOST|" frontend/.env.development
else
  # Not running in Codespaces (local devcontainer)
  DEFAULT_API_HOST="http://localhost:7091"
  echo "Setting VITE_API_HOST for local dev: $DEFAULT_API_HOST in frontend/.env.development"
  sed -i "s|VITE_API_HOST=.*|VITE_API_HOST=$DEFAULT_API_HOST|" frontend/.env.development
fi


mkdir -p model
if [ ! -d model/all-mpnet-base-v2 ]; then
    wget -q https://d3dg1063dc54p9.cloudfront.net/models/embeddings/mpnet-base-v2.zip -O model/mpnet-base-v2.zip
    unzip -q model/mpnet-base-v2.zip -d model
    rm model/mpnet-base-v2.zip
fi
pip install -r application/requirements.txt
cd frontend
npm install --include=dev