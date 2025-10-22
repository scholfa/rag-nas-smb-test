#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT_DIR"

# Ensure backend venv
cd backend
if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# Load .env from repo root if present (simple parser)
if [ -f "$ROOT_DIR/.env" ]; then
  echo "Loading environment from $ROOT_DIR/.env"
  # shellcheck disable=SC2046
  export $(grep -v '^#' "$ROOT_DIR/.env" | xargs || true)
fi

# Set sensible defaults for local backend
if [ -n "${DOCS_HOST_PATH:-}" ]; then
  export DOCS_DIR="${DOCS_HOST_PATH}"
elif [ -d "$ROOT_DIR/docs" ]; then
  export DOCS_DIR="$ROOT_DIR/docs"
else
  export DOCS_DIR="${DOCS_DIR:-$ROOT_DIR/docs}"
fi

export DATA_DIR="${DATA_DIR:-$ROOT_DIR/vectorstore}"
export OLLAMA_HOST="${OLLAMA_HOST:-http://localhost:11434}"

echo "Starting backend (local venv) with DOCS_DIR=$DOCS_DIR DATA_DIR=$DATA_DIR OLLAMA_HOST=$OLLAMA_HOST"
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
