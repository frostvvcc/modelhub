#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_DIR="$ROOT_DIR/.run"

kill_pid_file() {
  local pid_file="$1"
  local name="$2"

  if [[ ! -f "$pid_file" ]]; then
    echo "[skip] $name pid file not found"
    return 0
  fi

  local pid
  pid="$(cat "$pid_file")"
  if [[ -z "$pid" ]]; then
    rm -f "$pid_file"
    echo "[skip] $name pid file was empty"
    return 0
  fi

  if kill -0 "$pid" >/dev/null 2>&1; then
    echo "[stop] $name pid=$pid"
    kill "$pid" >/dev/null 2>&1 || true
    for _ in $(seq 1 15); do
      if ! kill -0 "$pid" >/dev/null 2>&1; then
        break
      fi
      sleep 1
    done
    if kill -0 "$pid" >/dev/null 2>&1; then
      echo "[stop] $name did not exit, sending SIGKILL"
      kill -9 "$pid" >/dev/null 2>&1 || true
    fi
  else
    echo "[skip] $name is not running"
  fi

  rm -f "$pid_file"
}

kill_pid_file "$RUN_DIR/frontend.pid" "Frontend"
kill_pid_file "$RUN_DIR/backend.pid" "Backend"
kill_pid_file "$RUN_DIR/chroma.pid" "ChromaDB"
kill_pid_file "$RUN_DIR/redis.pid" "Redis"
kill_pid_file "$RUN_DIR/mysql.pid" "MySQL"

echo "ModelHub dev stack stopped."
