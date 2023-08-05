#!/bin/bash

source .env

if [[ -n "$OPENAI_API_BASE" ]] && [[ -n "$OPENAI_API_VERSION" ]] && [[ -n "$AZURE_DEPLOYMENT_NAME" ]] && [[ -n "$AZURE_EMBEDDINGS_DEPLOYMENT_NAME" ]]; then
  echo "Running Azure Configuration"
  docker-compose -f docker-compose-azure.yaml build && docker-compose -f docker-compose-azure.yaml up
else
  echo "Running Plain Configuration"
  docker-compose build && docker-compose up
fi
