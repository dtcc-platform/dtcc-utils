#!/usr/bin/env bash
set -euo pipefail

# Check usage
if [ "$#" -ne 2 ]; then
  echo "Usage: $0 <repo> <version>"
  exit 1
fi

REPO="$1"
VERSION="$2"

# Create and switch to a temporary directory
DIR=$(mktemp -d)
echo "Working in temporary directory: $DIR"
cd "$DIR"

# Clone the repository
git clone "git@github.com:dtcc-platform/${REPO}.git"
cd "$REPO"

# Update on develop branch
echo "Checking out and updating develop branch..."
git checkout develop
git pull

# Update version in pyproject.toml to include 'dev'
if [[ "$OSTYPE" == "darwin"* ]]; then
  sed -i '' "s/\(version *= *\)\"[^\"]*\"/\1\"${VERSION}dev\"/" pyproject.toml
else
  sed -i "s/\(version *= *\)\"[^\"]*\"/\1\"${VERSION}dev\"/" pyproject.toml
fi

git commit -a -m "Bump version to ${VERSION}dev"
git tag "v${VERSION}dev"
git push origin develop --tags

# Update on main branch
echo "Switching to main branch and merging develop..."
git checkout main
git pull
git merge develop

# If there's a conflict in pyproject.toml, override with develop’s version
git checkout develop -- pyproject.toml
git add pyproject.toml
git commit --no-edit

# Remove 'dev' suffix and update dependency in pyproject.toml
if [[ "$OSTYPE" == "darwin"* ]]; then
  sed -i '' "s/\(version *= *\"${VERSION}\)dev\"/\1\"/" pyproject.toml
  sed -i '' 's#"dtcc-core@git+https://github.com/dtcc-platform/dtcc-core.git@develop",#"dtcc-core"#g' pyproject.toml
else
  sed -i "s/\(version *= *\"${VERSION}\)dev\"/\1\"/" pyproject.toml
  sed -i 's#"dtcc-core@git+https://github.com/dtcc-platform/dtcc-core.git@develop",#"dtcc-core"#g' pyproject.toml
fi

git commit -a -m "Bump version to ${VERSION}"
git tag "v${VERSION}"
git push origin main --tags

echo "Release process completed successfully."

# Optional: clean up the temporary directory
# rm -rf "$DIR"
