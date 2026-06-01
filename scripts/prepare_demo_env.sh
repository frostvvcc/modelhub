#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="$ROOT_DIR/ModelHub-backend"
PYTHON="$BACKEND_DIR/.venv/bin/python"

if [[ ! -x "$PYTHON" ]]; then
  echo "[error] Backend virtualenv not found: $PYTHON"
  echo "Run dependency installation first, then retry."
  exit 1
fi

echo "[1/5] Starting local services"
"$ROOT_DIR/scripts/start-dev.sh"

echo
echo "[2/5] Initializing providers and model metadata"
cd "$BACKEND_DIR"
"$PYTHON" scripts/init_provider_and_models.py

echo
echo "[3/5] Ensuring default public chat config and official knowledge base"
"$PYTHON" scripts/init_default_chat_config.py

echo
echo "[4/5] Seeding/vectorizing default demo knowledge base"
"$PYTHON" scripts/seed_default_knowledge_base.py

echo
echo "[5/5] Verifying external services without triggering Chroma default model downloads"
"$PYTHON" test_connections.py

echo
echo "[ok] Demo environment is ready."
echo "Frontend: http://127.0.0.1:5173"
echo "Backend:  http://127.0.0.1:5001/docs"
