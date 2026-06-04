"""
RAG（检索增强生成）核心引擎
包含文档解析、文本分块、向量检索（含混合检索）、重排序、Grounding 验证、运行时监控等子模块
"""
from app.services.rag.document_parser import DocumentParser, extract_text
from app.services.rag.chunking import ChunkStrategy, split_text_into_chunks
from app.services.rag.retrieval import VectorRetriever, RetrievalResult
from app.services.rag.monitor import RAGMonitor, RAGQueryMetrics, get_rag_monitor

__all__ = [
    "DocumentParser",
    "extract_text",
    "ChunkStrategy",
    "split_text_into_chunks",
    "VectorRetriever",
    "RetrievalResult",
    "RAGMonitor",
    "RAGQueryMetrics",
    "get_rag_monitor",
]
