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
}

# Handle parameters
ORGANIZATION="dtcc-platform"
DRY_RUN=false
REPO=""
VERSION=""

while [[ "$#" -gt 0 ]]; do
    case $1 in
        -h|--help) show_usage; exit 0 ;;
        -d|--dry-run) DRY_RUN=true; shift ;;
        -o|--org) ORGANIZATION="$2"; shift 2 ;;
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

# Function to update version based on platform
update_version() {
    local file="$1"
    local search="$2"
    local replace="$3"
    
    if [[ "$OSTYPE" == "darwin"* ]]; then
        # macOS version (BSD sed)
        execute sed -i '' -e "s|${search}|${replace}|g" "$file"
    else
        # Linux version (GNU sed)
        execute sed -i -e "s|${search}|${replace}|g" "$file"
    fi
}

# Function for regex pattern replacement (for more complex patterns)
update_with_pattern() {
    local file="$1"
    local pattern="$2"
    
    if [[ "$OSTYPE" == "darwin"* ]]; then
        # macOS version (BSD sed)
        execute sed -i '' -e "$pattern" "$file"
    else
        # Linux version (GNU sed)
        execute sed -i -e "$pattern" "$file"
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
CURRENT_VERSION=$(grep -oP 'version
