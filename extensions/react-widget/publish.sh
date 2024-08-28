#!/bin/bash
## chmod +x publish.sh   - to upgrade ownership
# Exit immediately if a command exits with a non-zero status.
set -e

# Define the function to update package.json and publish the package
cat package.json >> package_copy.json
publish_package() {
  PACKAGE_NAME=$1
  BUILD_COMMAND=$2
  # Update package name in package.json
  jq --arg name "$PACKAGE_NAME" '.name=$name' package.json > temp.json && mv temp.json package.json

  # Remove 'target' key if the package name is 'widget-react'
  if [ "$PACKAGE_NAME" = "docsgpt-react" ]; then
    jq 'del(.targets)' package.json > temp.json && mv temp.json package.json
  fi
  if [ -d "dist" ]; then
    echo "Deleting existing dist directory..."
    rm -rf dist
  fi
  # Increment version (patch by default)
  #npm version patch

  # Run the build command
  npm run "$BUILD_COMMAND"

  # Publish to npm
  npm pack
  echo "Published ${PACKAGE_NAME}"
}

# Publish widget package
publish_package "docsgpt" "build"

# Publish widget-react package
publish_package "docsgpt-react" "build:react"

# Clean up
mv package_copy.json package.json
rm -rf package_copy.json
echo "---Process completed---"