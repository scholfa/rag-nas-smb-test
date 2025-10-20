#!/usr/bin/env bash
set -euo pipefail

echo "=== RAG Project Smoke Test ==="

# Check Docker
if ! docker info > /dev/null 2>&1; then
  echo "❌ Docker not running or not accessible"
  exit 1
fi
echo "✅ Docker is running"

# Choose compose command
if docker compose version >/dev/null 2>&1; then
  COMPOSE_CMD="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE_CMD="docker-compose"
else
  echo "ERROR: docker compose not found"
  exit 1
fi

echo "Using compose: $COMPOSE_CMD"

echo "--- Services ---"
$COMPOSE_CMD ps || true

echo "--- Checking HTTP endpoints ---"
check_http() {
  url=$1
  name=$2
  if curl -s --max-time 5 "$url" > /dev/null; then
    echo "✅ $name is responding: $url"
  else
    echo "❌ $name not responding: $url"
  fi
}

check_http http://localhost:8000/health Backend
check_http http://localhost:3000 Frontend
check_http http://localhost:11434/api/tags Ollama

echo "--- Inspecting backend container for /docs (if running) ---"
BACKEND_CONTAINER=$(docker ps --filter "name=rag-backend" --format "{{.Names}}")
if [ -n "$BACKEND_CONTAINER" ]; then
  echo "Found backend container: $BACKEND_CONTAINER"
  echo "Listing /docs inside container (if present):"
  docker exec -it "$BACKEND_CONTAINER" sh -c 'ls -la /docs || echo "/docs not present"'
else
  echo "Backend container not running, skipping /docs inspection"
fi

echo "=== Smoke Test Complete ==="
