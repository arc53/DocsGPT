#!/bin/bash
## chmod +x publish.sh - to upgrade ownership
set -e
cat package.json >> package_copy.json
publish_package() {
  PACKAGE_NAME=$1
  BUILD_COMMAND=$2
  # Update package name in package.json
  jq --arg name "$PACKAGE_NAME" '.name=$name' package.json > temp.json && mv temp.json package.json

  # Remove 'target' key if the package name is 'docsgpt-react'
  if [ "$PACKAGE_NAME" = "docsgpt-react" ]; then
    jq 'del(.targets)' package.json > temp.json && mv temp.json package.json
  fi

  if [ -d "dist" ]; then
    echo "Deleting existing dist directory..."
    rm -rf dist
  fi

  npm version patch

  npm run "$BUILD_COMMAND"

  # Publish to npm
  npm publish
  echo "Published ${PACKAGE_NAME}"
}

# Publish docsgpt package
publish_package "docsgpt" "build"

# Publish docsgpt-react package
publish_package "docsgpt-react" "build:react"

# Clean up
mv package_copy.json package.json
rm -rf package_copy.json
echo "---Process completed---"