"""
RAG（检索增强生成）核心引擎
包含文档解析、文本分块、向量检索（含混合检索）等子模块
"""
from app.services.rag.document_parser import DocumentParser, extract_text
from app.services.rag.chunking import ChunkStrategy, split_text_into_chunks
from app.services.rag.retrieval import VectorRetriever, RetrievalResult

__all__ = [
    "DocumentParser",
    "extract_text",
    "ChunkStrategy",
    "split_text_into_chunks",
    "VectorRetriever",
    "RetrievalResult",
]
