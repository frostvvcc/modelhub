#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_DIR="$ROOT_DIR/.run"
LOG_DIR="$RUN_DIR/logs"
BACKEND_DIR="$ROOT_DIR/ModelHub-backend"
FRONTEND_DIR="$ROOT_DIR/ModelHub-frontend"

mkdir -p "$RUN_DIR" "$LOG_DIR" "$RUN_DIR/redis" "$RUN_DIR/chroma"

is_port_open() {
  local port="$1"
  lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1
}

wait_for_port() {
  local port="$1"
  local name="$2"
  local seconds="${3:-40}"

  for _ in $(seq 1 "$seconds"); do
    if is_port_open "$port"; then
      echo "[ok] $name is listening on $port"
      return 0
    fi
    sleep 1
  done

  echo "[warn] $name did not open port $port within ${seconds}s"
  return 1
}

start_mysql() {
  if is_port_open 3307; then
    echo "[skip] MySQL is already listening on 3307"
    return 0
  fi

  local mysql_bin="${MYSQLD_BIN:-/opt/homebrew/opt/mysql/bin/mysqld}"
  local mysql_data="${MYSQL_DATA_DIR:-/opt/homebrew/var/mysql}"
  if [[ ! -x "$mysql_bin" ]]; then
    echo "[warn] mysqld not found at $mysql_bin. Start MySQL manually or set MYSQLD_BIN."
    return 0
  fi

  echo "[start] MySQL on 127.0.0.1:3307"
  nohup "$mysql_bin" \
    --datadir="$mysql_data" \
    --socket="$RUN_DIR/mysql.sock" \
    --pid-file="$RUN_DIR/mysql.pid" \
    --port=3307 \
    --bind-address=127.0.0.1 \
    --mysqlx=0 \
    --log-error="$LOG_DIR/mysql.err" \
    >/dev/null 2>&1 &
  echo "$!" > "$RUN_DIR/mysql.pid"
  disown "$!" >/dev/null 2>&1 || true
  wait_for_port 3307 "MySQL" 30 || true
}

start_redis() {
  if is_port_open 6379; then
    echo "[skip] Redis is already listening on 6379"
    return 0
  fi

  if ! command -v redis-server >/dev/null 2>&1; then
    echo "[warn] redis-server not found. Redis is optional for local dev, but caching will be disabled."
    return 0
  fi

  echo "[start] Redis on 127.0.0.1:6379"
  redis-server \
    --daemonize yes \
    --bind 127.0.0.1 \
    --port 6379 \
    --dir "$RUN_DIR/redis" \
    --logfile "$LOG_DIR/redis.log" \
    --pidfile "$RUN_DIR/redis.pid"
  wait_for_port 6379 "Redis" 20 || true
}

start_chroma() {
  if is_port_open 8000; then
    echo "[skip] ChromaDB is already listening on 8000"
    return 0
  fi

  if [[ ! -x "$BACKEND_DIR/.venv/bin/chroma" ]]; then
    echo "[warn] Chroma CLI not found. Run: cd ModelHub-backend && .venv/bin/pip install -r requirements-dev.txt"
    return 1
  fi

  echo "[start] ChromaDB on http://127.0.0.1:8000"
  nohup bash -c "
    cd "$BACKEND_DIR"
    exec "$BACKEND_DIR/.venv/bin/chroma" run --path "$RUN_DIR/chroma" --host 127.0.0.1 --port 8000
  " > "$LOG_DIR/chroma.log" 2>&1 &
  echo "$!" > "$RUN_DIR/chroma.pid"
  disown "$!" >/dev/null 2>&1 || true
  wait_for_port 8000 "ChromaDB" 40 || true
}

start_backend() {
  if is_port_open 5001; then
    echo "[skip] Backend is already listening on 5001"
    return 0
  fi

  if [[ ! -x "$BACKEND_DIR/.venv/bin/uvicorn" ]]; then
    echo "[warn] Backend venv not ready. Run: cd ModelHub-backend && python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt"
    return 1
  fi

  echo "[start] Backend on http://127.0.0.1:5001"
  nohup bash -c "
    cd "$BACKEND_DIR"
    exec "$BACKEND_DIR/.venv/bin/uvicorn" main_fastapi:app --host 127.0.0.1 --port 5001
  " > "$LOG_DIR/backend.log" 2>&1 &
  echo "$!" > "$RUN_DIR/backend.pid"
  disown "$!" >/dev/null 2>&1 || true
  wait_for_port 5001 "Backend" 40 || true
}

start_frontend() {
  if is_port_open 5173; then
    echo "[skip] Frontend is already listening on 5173"
    return 0
  fi

  if [[ ! -d "$FRONTEND_DIR/node_modules" ]]; then
    echo "[warn] Frontend dependencies not installed. Run: cd ModelHub-frontend && npm install"
    return 1
  fi

  echo "[start] Frontend on http://127.0.0.1:5173"
  nohup bash -c "
    cd "$FRONTEND_DIR"
    exec npm run dev -- --host 127.0.0.1 --port 5173
  " > "$LOG_DIR/frontend.log" 2>&1 &
  echo "$!" > "$RUN_DIR/frontend.pid"
  disown "$!" >/dev/null 2>&1 || true
  wait_for_port 5173 "Frontend" 40 || true
}

start_mysql
start_redis
start_chroma
start_backend
start_frontend

echo
echo "ModelHub dev stack is starting."
echo "Frontend: http://127.0.0.1:5173"
echo "Backend:  http://127.0.0.1:5001/docs"
echo "Logs:     $LOG_DIR"
echo "Stop:     ./scripts/stop-dev.sh"
