#!/bin/bash

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$ROOT_DIR/ModelHub-backend/.env"

if [ -f "$ENV_FILE" ]; then
    set -a
    . "$ENV_FILE"
    set +a
fi

DB_PORT="${DB_PORT:-3306}"
REDIS_PORT="${REDIS_PORT:-6379}"
CHROMA_SERVER_HOST="${CHROMA_SERVER_HOST:-127.0.0.1}"
CHROMA_SERVER_PORT="${CHROMA_SERVER_PORT:-8000}"

echo "🔍 检查本地服务状态..."
echo ""

# 检查MySQL
echo "1. MySQL (端口 ${DB_PORT}):"
if lsof -i :"$DB_PORT" > /dev/null 2>&1; then
    echo "   ✅ MySQL 正在运行"
    mysql --version 2>/dev/null || echo "   ⚠️  无法获取版本信息"
else
    echo "   ❌ MySQL 未运行"
    echo "   启动: brew services start mysql"
fi

echo ""

# 检查Redis
echo "2. Redis (端口 ${REDIS_PORT}):"
if lsof -i :"$REDIS_PORT" > /dev/null 2>&1; then
    echo "   ✅ Redis 正在运行"
    if command -v redis-cli > /dev/null 2>&1; then
        redis-cli ping 2>/dev/null && echo "   ✅ Redis 连接正常" || echo "   ⚠️  Redis 连接异常"
    fi
else
    echo "   ❌ Redis 未运行"
    echo "   启动: brew services start redis"
    echo "   或: redis-server"
fi

echo ""

# 检查ChromaDB
echo "3. ChromaDB (${CHROMA_SERVER_HOST}:${CHROMA_SERVER_PORT}):"
if lsof -i :"$CHROMA_SERVER_PORT" > /dev/null 2>&1; then
    echo "   ✅ ChromaDB 正在运行"
    if curl -s "http://${CHROMA_SERVER_HOST}:${CHROMA_SERVER_PORT}/api/v2/heartbeat" > /dev/null 2>&1 || \
       curl -s "http://${CHROMA_SERVER_HOST}:${CHROMA_SERVER_PORT}/api/v1/heartbeat" > /dev/null 2>&1; then
        echo "   ✅ ChromaDB 连接正常"
    else
        echo "   ⚠️  ChromaDB 连接异常"
    fi
else
    echo "   ❌ ChromaDB 未运行"
    echo "   启动: chroma run --host ${CHROMA_SERVER_HOST} --port ${CHROMA_SERVER_PORT}"
    echo "   或: docker run -d -p ${CHROMA_SERVER_PORT}:8000 chromadb/chroma"
fi

echo ""
echo "=========================================="
