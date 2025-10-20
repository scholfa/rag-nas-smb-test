#!/usr/bin/env bash
# Cross-platform (Linux/macOS) helper to start the project with docker-compose
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT_DIR"

# pick a docker-compose command that exists
if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  COMPOSE_CMD="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE_CMD="docker-compose"
else
  echo "ERROR: neither 'docker compose' nor 'docker-compose' found in PATH"
  exit 1
fi

# If an override example exists and no override file is present, copy it
if [ -f docker-compose.override.yml.example ] && [ ! -f docker-compose.override.yml ]; then
  echo "Using example override file -> docker-compose.override.yml"
  cp docker-compose.override.yml.example docker-compose.override.yml
fi

echo "Starting services with: $COMPOSE_CMD up --build"
eval "$COMPOSE_CMD up --build"
