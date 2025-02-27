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

# Attempt merge
if ! git merge develop; then
  echo "Merge conflict detected. Resolving by taking develop's version of pyproject.toml..."
  # Use --theirs to pick develop's version for the conflicting file
  git checkout --theirs -- pyproject.toml
  git add pyproject.toml
  git commit -m "Merge develop into main, overriding pyproject.toml with develop version"
fi

# Remove 'dev' suffix and update dependency in pyproject.toml
if [[ "$OSTYPE" == "darwin"* ]]; then
  sed -i '' "s/\(version *= *\"${VERSION}\)dev\"/\1\"/" pyproject.toml
  #sed -i '' 's#"dtcc-core@git+https://github.com/dtcc-platform/dtcc-core.git@develop",#"dtcc-core"#g' pyproject.toml
  sed -i '' 's/"\([^@"]*\)@git[^"]*"/"\1"/g' pyproject.toml

else
  sed -i "s/\(version *= *\"${VERSION}\)dev\"/\1\"/" pyproject.toml
  #sed -i 's#"dtcc-core@git+https://github.com/dtcc-platform/dtcc-core.git@develop",#"dtcc-core"#g' pyproject.toml
  sed -i 's/"\([^@"]*\)@git[^"]*"/"\1"/g' pyproject.toml

fi

git commit -a -m "Bump version to ${VERSION}"
git tag "v${VERSION}"
git push origin main --tags

echo "Release process completed successfully."
echo "Proceed to 1) https://github.com/dtcc-platform/$REPO/releases to actually release on Github and 2) https://github.com/dtcc-platform/$REPO/actions/workflows/ci-wheels.yaml to run the dispatch workflow on main for PyPI release!"
# Optional: clean up the temporary directory
rm -rf "$DIR"
