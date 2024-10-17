#!/bin/bash

# Load environment variables from the .env file
source .env

# Function to handle errors and exit with an error message
handle_error() {
  echo "Error: $1" >&2
  exit 1
}

# Check if required Azure-related environment variables are set
if [[ -n "$OPENAI_API_BASE" ]] && [[ -n "$OPENAI_API_VERSION" ]] && [[ -n "$AZURE_DEPLOYMENT_NAME" ]] && [[ -n "$AZURE_EMBEDDINGS_DEPLOYMENT_NAME" ]]; then
  echo "Running Azure Configuration"
  
  # Build the Docker images with the Azure configuration
  docker compose -f docker-compose-azure.yaml build || handle_error "Failed to build the Azure Docker images"
  
  # Bring up the services using the Azure-specific docker-compose file
  docker compose -f docker-compose-azure.yaml up --build -d || handle_error "Failed to start the Azure Docker containers"
  
else
  echo "Running Plain Configuration"
  
  # Build the Docker images with the default configuration
  docker compose build || handle_error "Failed to build the default Docker images"
  
  # Bring up the services using the default docker-compose file
  docker compose up --build -d || handle_error "Failed to start the default Docker containers"
fi

# Gracefully shut down containers if needed
# Uncomment the following line to bring down the containers after use (optional)
# docker compose down || handle_error "Failed to stop and remove containers"

