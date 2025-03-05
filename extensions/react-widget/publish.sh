#!/bin/bash
set -e

# Create backup of original files
cp package.json package_original.json
cp package-lock.json package-lock_original.json

# Store the latest version after publishing
LATEST_VERSION=""

# Check if a specific version was provided
if [ "$1" ]; then
    VERSION_UPDATE_TYPE="$1"
    echo "Using custom version update: $VERSION_UPDATE_TYPE"
else
    VERSION_UPDATE_TYPE="patch"
    echo "No version specified, defaulting to patch update"
fi

publish_package() {
    PACKAGE_NAME=$1
    BUILD_COMMAND=$2
    IS_REACT=$3

    echo "Preparing to publish ${PACKAGE_NAME}..."
    
    # Restore original package.json state before each publish
    cp package_original.json package.json
    cp package-lock_original.json package-lock.json

    # Update package name in package.json
    jq --arg name "$PACKAGE_NAME" '.name=$name' package.json > temp.json && mv temp.json package.json

    # Handle targets based on package type
    if [ "$IS_REACT" = "true" ]; then
        echo "Removing targets for React library build..."
        jq 'del(.targets)' package.json > temp.json && mv temp.json package.json
    fi

    # Clean dist directory
    if [ -d "dist" ]; then
        echo "Cleaning dist directory..."
        rm -rf dist
    fi

    # Update version based on input parameter or default to patch
    if [[ "$VERSION_UPDATE_TYPE" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
        # If full version number is provided (e.g., 0.5.0)
        LATEST_VERSION=$(npm version "$VERSION_UPDATE_TYPE" --no-git-tag-version)
    else
        # If update type is provided (patch, minor, major)
        LATEST_VERSION=$(npm version "$VERSION_UPDATE_TYPE" --no-git-tag-version)
    fi
    
    echo "New version: ${LATEST_VERSION}"

    # Build package
    npm run "$BUILD_COMMAND"

    # Publish package
    npm publish

    echo "Successfully published ${PACKAGE_NAME} version ${LATEST_VERSION}"
}

# First publish docsgpt (HTML bundle)
publish_package "docsgpt" "build" "false"

# Then publish docsgpt-react (React library)
publish_package "docsgpt-react" "build:react" "true"

# Restore original state but keep the updated version
cp package_original.json package.json
cp package-lock_original.json package-lock.json

# Update the version in the final package.json
jq --arg version "${LATEST_VERSION#v}" '.version=$version' package.json > temp.json && mv temp.json package.json

# Run npm install to update package-lock-only
npm install --package-lock-only

# Cleanup backup files
rm -f package_original.json
rm -f package-lock_original.json
rm -f temp.json

echo "---Process completed---"
echo "Final version in package.json: $(jq -r '.version' package.json)"
echo "Final version in package-lock.json: $(jq -r '.version' package-lock.json)"

