#!/usr/bin/env bash
# Script for preparing Git releases
# Usage: ./release.sh REPO VERSION [OPTIONS]

# Exit immediately if a command exits with a non-zero status
set -e

# Parse command line options
show_usage() {
    echo "Usage: $0 REPO VERSION [OPTIONS]"
    echo "Example: $0 dtcc-core 0.9.0"
    echo ""
    echo "Options:"
    echo "  -h, --help     Show this help message"
    echo "  -d, --dry-run  Show what would happen without making changes"
    echo "  -o, --org ORG  Specify GitHub organization (default: dtcc-platform)"
    echo "  -f, --force    Force overwrite main with develop's pyproject.toml on conflict"
}

# Handle parameters
ORGANIZATION="dtcc-platform"
DRY_RUN=false
FORCE=false
REPO=""
VERSION=""

while [[ "$#" -gt 0 ]]; do
    case $1 in
        -h|--help) show_usage; exit 0 ;;
        -d|--dry-run) DRY_RUN=true; shift ;;
        -o|--org) ORGANIZATION="$2"; shift 2 ;;
        -f|--force) FORCE=true; shift ;;
        *)
            if [ -z "$REPO" ]; then REPO="$1"
            elif [ -z "$VERSION" ]; then VERSION="$1"
            else echo "Unknown parameter: $1"; show_usage; exit 1; fi
            shift ;;
    esac
done

# Validate required parameters
if [ -z "$REPO" ] || [ -z "$VERSION" ]; then
    echo "Error: Missing required arguments"
    show_usage
    exit 1
fi

# Create and track temporary directory
TEMP_DIR=$(mktemp -d)
echo "Working in: $TEMP_DIR"
trap 'echo "Cleaning up $TEMP_DIR"; rm -rf "$TEMP_DIR"' EXIT

# Function to execute commands (or simulate in dry-run mode)
execute() {
    if [ "$DRY_RUN" = true ]; then
        echo "[DRY RUN] Would execute: $*"
    else
        echo "Executing: $*"
        "$@"
    fi
}

# Function for sed operations that works on both Linux and macOS
sed_command() {
    local file="$1"
    local pattern="$2"
    
    if [[ "$OSTYPE" == "darwin"* ]]; then
        # macOS requires an empty string after -i
        execute sed -i "" "$pattern" "$file"
    else
        # Linux version
        execute sed -i "$pattern" "$file"
    fi
}

# Clone repository
cd "$TEMP_DIR"
execute git clone "git@github.com:$ORGANIZATION/$REPO.git"
cd "$REPO" || { echo "Failed to enter repo directory"; exit 1; }

# Update develop branch
echo "=== Updating develop branch ==="
execute git checkout develop
execute git pull

# Get current version for better logging
CURRENT_VERSION=$(grep 'version *=' pyproject.toml | sed 's/.*version *= *"\([^"]*\)".*/\1/' || echo "unknown")
DEV_VERSION="${VERSION}dev"
echo "Current: $CURRENT_VERSION → New: $DEV_VERSION"

# Update version in develop
sed_command "pyproject.toml" "s/version *= *\"[^\"]*\"/version = \"${DEV_VERSION}\"/"

# Commit and tag changes in develop
if ! execute git diff --quiet; then
    execute git commit -a -m "Bump version to $DEV_VERSION"
fi
execute git tag "v$DEV_VERSION"
execute git push origin develop --tags

# Save a copy of the develop pyproject.toml
cp pyproject.toml pyproject.toml.develop

# Update main branch
echo "=== Updating main branch ==="
execute git checkout main
execute git pull

# Handle merge with conflict resolution strategy
echo "=== Merging develop into main ==="
if [ "$FORCE" = true ]; then
    # Try to merge, but if conflict occurs, use develop's pyproject.toml
    git merge develop || true
    
    if git status | grep -q "Unmerged paths"; then
        echo "Merge conflict detected, resolving with develop's version..."
        cp pyproject.toml.develop pyproject.toml
        git add pyproject.toml
        git commit -m "Merge develop into main, using develop's pyproject.toml"
    fi
else
    # Alternative approach - don't merge, just cherry-pick what we need
    echo "Skipping merge, applying changes directly..."
    cp pyproject.toml.develop pyproject.toml
    git add pyproject.toml
fi

# Update to release version (remove dev suffix)
sed_command "pyproject.toml" "s/version *= *\"${VERSION}dev\"/version = \"${VERSION}\"/"

# Replace any Git dependencies with PyPI versions
sed_command "pyproject.toml" "s|\"\\([^\"]*\\)@git+https://github.com/[^\"]*\\.git@develop\",|\"\\1\"|g"

# Commit and tag release
git add pyproject.toml
execute git commit -m "Bump version to $VERSION"
execute git tag "v$VERSION"
execute git push origin main --tags

echo "=== Release preparation completed successfully! ==="
