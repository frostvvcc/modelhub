"""
优化的ChromaDB客户端管理
使用单例模式复用客户端连接
"""
import os
import chromadb
import logging
from threading import Lock
from typing import Optional
from app.config import settings
from chromadb.config import Settings

logger = logging.getLogger(__name__)

# 全局客户端实例
_chroma_client: Optional[chromadb.HttpClient] = None
_client_lock = Lock()

def get_chromadb_client() -> Optional[chromadb.HttpClient]:
    """
    获取ChromaDB客户端（单例模式）
    避免每次调用都创建新连接
    """
    global _chroma_client

    if _chroma_client is None:
        with _client_lock:
            # 双重检查锁定
            if _chroma_client is None:
                try:
                    logger.info(f"创建ChromaDB客户端: {settings.chroma_server_host}:{settings.chroma_server_port}")

                    # 确保本地连接不走系统代理（httpx 可能受 macOS 代理配置干扰）
                    os.environ.setdefault("NO_PROXY", "127.0.0.1,localhost")
                    os.environ.setdefault("no_proxy", "127.0.0.1,localhost")

                    _chroma_client = chromadb.HttpClient(
                        host=settings.chroma_server_host,
                        port=settings.chroma_server_port
                    )

                    # 检查连接状态
                    heartbeat = _chroma_client.heartbeat()
                    logger.info(f"ChromaDB连接成功: {heartbeat}")

                except Exception as e:
                    logger.error(f"ChromaDB连接失败: {str(e)}")
                    return None

    return _chroma_client

def reset_chromadb_client():
    """重置ChromaDB客户端（用于重连）"""
    global _chroma_client
    with _client_lock:
        _chroma_client = None
        logger.info("ChromaDB客户端已重置")

