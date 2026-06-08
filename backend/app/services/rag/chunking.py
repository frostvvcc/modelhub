"""
文本分块策略模块
支持 fixed、sentence、markdown、parent_child、semantic、contextual 六种策略

Contextual Retrieval (Anthropic, 2024):
  为每个 chunk 前置文档级上下文摘要，提升检索时的语义理解。
  chunk 被嵌入时带有"这是关于XX的文档中的一段"前缀，避免孤立 chunk 丢失语境。
"""
import re
from dataclasses import dataclass
from enum import Enum
from typing import List

import numpy as np
from app.utils.logger_config import get_logger

logger = get_logger(__name__)


class ChunkStrategy(str, Enum):
    FIXED = "fixed"
    SENTENCE = "sentence"
    MARKDOWN = "markdown"
    PARENT_CHILD = "parent_child"
    SEMANTIC = "semantic"
    CONTEXTUAL = "contextual"


@dataclass
class ParentChildChunk:
    """父子分块结果：child 用于向量检索（精度高），parent 用于喂给 LLM（上下文完整）"""
    child_content: str
    parent_content: str
    parent_index: int
    child_index: int


def split_text_into_chunks(
    text: str,
    strategy: ChunkStrategy = ChunkStrategy.FIXED,
    chunk_size: int = 800,
    overlap: int = 150,
) -> List[str]:
    """
    将文本分割成块。parent_child 策略请直接调用 split_parent_child()。
    """
    if not text or not text.strip():
        return []

    text = text.strip()

    if strategy == ChunkStrategy.CONTEXTUAL:
        raise ValueError("CONTEXTUAL 策略需要 LLM，请直接调用 split_contextual()")

    if strategy == ChunkStrategy.SEMANTIC:
        raise ValueError("SEMANTIC 策略需要 embedding_fn，请直接调用 split_semantic()")

    if strategy == ChunkStrategy.PARENT_CHILD:
        pc = split_parent_child(text, parent_size=chunk_size, child_size=max(100, chunk_size // 4))
        return [c.child_content for c in pc]
    if strategy == ChunkStrategy.MARKDOWN:
        return _chunk_by_markdown(text, chunk_size)
    elif strategy == ChunkStrategy.SENTENCE:
        return _chunk_by_sentence(text, chunk_size, overlap)
    else:
        return _chunk_fixed(text, chunk_size, overlap)


def split_parent_child(
    text: str,
    parent_size: int = 800,
    child_size: int = 200,
    parent_overlap: int = 100,
    child_overlap: int = 50,
) -> List[ParentChildChunk]:
    """
    父子分块：Small-to-Big 检索策略。

    先切出大块（parent，800 字），再把每个 parent 切成小块（child，200 字）。
    检索时用 child embedding 做精准向量匹配，命中后返回 parent 给 LLM 保证上下文完整。
    """
    if not text or not text.strip():
        return []

    text = text.strip()
    parents = _chunk_fixed(text, parent_size, parent_overlap)

    results: List[ParentChildChunk] = []
    for pi, parent in enumerate(parents):
        if len(parent) <= child_size:
            results.append(ParentChildChunk(
                child_content=parent, parent_content=parent,
                parent_index=pi, child_index=0,
            ))
        else:
            children = _chunk_fixed(parent, child_size, child_overlap)
            for ci, child in enumerate(children):
                results.append(ParentChildChunk(
                    child_content=child, parent_content=parent,
                    parent_index=pi, child_index=ci,
                ))

    logger.info(
        f"父子分块: {len(parents)} 个 parent → {len(results)} 个 child, "
        f"parent_size={parent_size}, child_size={child_size}"
    )
    return results


def split_semantic(
    text: str,
    embedding_fn,
    max_chunk_size: int = 1000,
    similarity_threshold: float = 0.5,
    min_sentences: int = 3,
) -> List[str]:
    """
    语义分块：基于相邻句子 embedding 余弦相似度在语义边界处切分。

    原理：相邻句子 embedding 相似度高表示语义连续，
    相似度骤降处即为话题切换点，在此处切分保证语义完整性。

    Args:
        text: 待分块文本
        embedding_fn: 批量 embedding 函数，签名 (List[str]) -> List[List[float]]
        max_chunk_size: 单个 chunk 最大字符数
        similarity_threshold: 低于此阈值视为语义边界
        min_sentences: chunk 最少包含的句子数
    """
    if not text or not text.strip():
        return []

    text = text.strip()

    sentence_endings = re.compile(r'(?<=[。！？.!?\n])\s*')
    sentences = [s.strip() for s in sentence_endings.split(text) if s.strip()]

    if len(sentences) <= min_sentences:
        return [text] if text else []

    try:
        embeddings = embedding_fn(sentences)
        emb_array = np.array(embeddings, dtype=np.float32)
    except Exception as e:
        logger.warning(f"语义分块 embedding 失败，降级为固定分块: {e}")
        return _chunk_fixed(text, max_chunk_size, 150)

    norms = np.linalg.norm(emb_array, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1, norms)
    normalized = emb_array / norms
    similarities = np.sum(normalized[:-1] * normalized[1:], axis=1)

    split_points = [0]
    for i, sim in enumerate(similarities):
        if sim < similarity_threshold:
            split_points.append(i + 1)
    split_points.append(len(sentences))

    raw_chunks = []
    for start_idx, end_idx in zip(split_points[:-1], split_points[1:]):
        chunk_text = ''.join(sentences[start_idx:end_idx]).strip()
        if not chunk_text:
            continue
        if len(chunk_text) > max_chunk_size:
            raw_chunks.extend(_chunk_fixed(chunk_text, max_chunk_size, 0))
        else:
            raw_chunks.append(chunk_text)

    merged = []
    buffer = ""
    for chunk in raw_chunks:
        if len(buffer) + len(chunk) <= max_chunk_size:
            buffer += chunk
        else:
            if buffer:
                merged.append(buffer)
            buffer = chunk
    if buffer:
        merged.append(buffer)

    logger.info(
        f"语义分块: {len(sentences)} 句 → {len(merged)} 块, "
        f"threshold={similarity_threshold}, 切分点={len(split_points)-2}"
    )
    return merged


# ------------------------------------------------------------------
# 固定大小分块（原有逻辑，完全兼容）
# ------------------------------------------------------------------

def _chunk_fixed(text: str, chunk_size: int, overlap: int) -> List[str]:
    if not text:
        return []
    if len(text) <= chunk_size:
        return [text]

    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        if end < len(text):
            for delimiter in ['\n\n', '\n', '。', '！', '？', '.', '!', '?']:
                pos = text.rfind(delimiter, start, end)
                if pos != -1 and pos > start + chunk_size // 2:
                    end = pos + len(delimiter)
                    break
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        start = end - overlap if end < len(text) else end

    logger.info(f"固定分块: 原始长度={len(text)}, 分割成 {len(chunks)} 块")
    return chunks


# ------------------------------------------------------------------
# 句子边界分块
# ------------------------------------------------------------------

def _chunk_by_sentence(text: str, chunk_size: int, overlap: int) -> List[str]:
    """先按句子切分，再合并到不超过 chunk_size"""
    sentence_endings = re.compile(r'(?<=[。！？.!?\n])\s*')
    sentences = [s.strip() for s in sentence_endings.split(text) if s.strip()]

    chunks, current, current_len = [], [], 0
    for sent in sentences:
        sent_len = len(sent)
        if current_len + sent_len > chunk_size and current:
            chunks.append(''.join(current))
            # overlap：保留末尾若干句子
            overlap_text = ''.join(current)[-overlap:] if overlap > 0 else ''
            current = [overlap_text, sent] if overlap_text else [sent]
            current_len = len(overlap_text) + sent_len
        else:
            current.append(sent)
            current_len += sent_len
    if current:
        chunks.append(''.join(current))

    logger.info(f"句子分块: 原始长度={len(text)}, 分割成 {len(chunks)} 块")
    return chunks


# ------------------------------------------------------------------
# Markdown 标题层级分块
# ------------------------------------------------------------------

def _chunk_by_markdown(text: str, chunk_size: int) -> List[str]:
    """
    按 Markdown 标题（# ## ###）切分，每个标题段落作为一个 chunk。
    若段落超过 chunk_size，进一步按固定大小切分。
    """
    heading_pattern = re.compile(r'^(#{1,6})\s+(.+)$', re.MULTILINE)
    positions = [m.start() for m in heading_pattern.finditer(text)]

    if not positions:
        return _chunk_fixed(text, chunk_size, 0)

    segments = []
    for i, pos in enumerate(positions):
        end = positions[i + 1] if i + 1 < len(positions) else len(text)
        segments.append(text[pos:end].strip())

    chunks = []
    for seg in segments:
        if len(seg) <= chunk_size:
            chunks.append(seg)
        else:
            chunks.extend(_chunk_fixed(seg, chunk_size, 0))

    logger.info(f"Markdown 分块: 原始长度={len(text)}, 分割成 {len(chunks)} 块")
    return chunks


# ------------------------------------------------------------------
# Contextual Retrieval (Anthropic, 2024)
# ------------------------------------------------------------------

@dataclass
class ContextualChunk:
    """上下文增强分块：包含原始内容和带上下文前缀的版本"""
    original_content: str
    contextualized_content: str
    context_prefix: str
    chunk_index: int


async def _generate_chunk_context(
    document_text: str,
    chunk_text: str,
    chunk_index: int,
    model: str = None,
) -> str:
    """
    用 LLM 为单个 chunk 生成上下文前缀。
    输入：完整文档 + 当前 chunk → 输出：一段简短的上下文说明。
    """
    from openai import AsyncOpenAI
    from app.config import settings
    import httpx

    model = model or settings.rag_llm_model
    client = AsyncOpenAI(
        api_key=settings.rag_llm_api_key or settings.embedding_api_key,
        base_url=settings.rag_llm_base_url or settings.embedding_base_url,
        timeout=httpx.Timeout(timeout=30.0),
        max_retries=1,
    )

    doc_preview = document_text[:1500]

    prompt = (
        "这是一份文档的全文概要和其中的一个片段。"
        "请用 1-2 句话简要说明这个片段在文档中的位置和上下文，"
        "以便单独看到这个片段时也能理解它的背景。\n"
        "只输出上下文说明，不要其他内容。\n\n"
        f"<document>\n{doc_preview}\n</document>\n\n"
        f"<chunk>\n{chunk_text[:500]}\n</chunk>"
    )

    try:
        resp = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=100,
            temperature=0.0,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        logger.warning(f"Chunk #{chunk_index} 上下文生成失败: {e}")
        return ""


async def split_contextual(
    text: str,
    chunk_size: int = 800,
    overlap: int = 150,
    base_strategy: ChunkStrategy = ChunkStrategy.FIXED,
    model: str = None,
    max_concurrency: int = 10,
) -> List[ContextualChunk]:
    """
    Contextual Retrieval 分块 (Anthropic, 2024)：

    1. 先用基础策略（fixed/sentence/markdown）切分文本
    2. 对每个 chunk 用 LLM 生成上下文前缀
    3. 将前缀 + 原文拼接为 contextualized_content，用于后续 embedding

    优势：
    - 解决孤立 chunk 语义不完整的问题
    - 检索时 chunk 自带文档上下文，召回率提升 ~20% (Anthropic 实测)
    - 与 BM25 + 向量混合检索组合效果更佳

    Args:
        text: 完整文档文本
        chunk_size: 分块大小
        overlap: 重叠字符数
        base_strategy: 基础分块策略
        model: LLM 模型名
        max_concurrency: 并行生成上下文的最大并发数
    """
    import asyncio

    if not text or not text.strip():
        return []

    # Step 1: 基础分块
    if base_strategy == ChunkStrategy.MARKDOWN:
        raw_chunks = _chunk_by_markdown(text.strip(), chunk_size)
    elif base_strategy == ChunkStrategy.SENTENCE:
        raw_chunks = _chunk_by_sentence(text.strip(), chunk_size, overlap)
    else:
        raw_chunks = _chunk_fixed(text.strip(), chunk_size, overlap)

    if not raw_chunks:
        return []

    # Step 2: 并行生成上下文前缀
    semaphore = asyncio.Semaphore(max_concurrency)

    async def _gen_context(idx: int, chunk: str) -> ContextualChunk:
        async with semaphore:
            prefix = await _generate_chunk_context(text, chunk, idx, model)
            if prefix:
                contextualized = f"{prefix}\n\n{chunk}"
            else:
                contextualized = chunk
            return ContextualChunk(
                original_content=chunk,
                contextualized_content=contextualized,
                context_prefix=prefix,
                chunk_index=idx,
            )

    results = await asyncio.gather(
        *[_gen_context(i, c) for i, c in enumerate(raw_chunks)],
        return_exceptions=True,
    )

    contextual_chunks = []
    for r in results:
        if isinstance(r, ContextualChunk):
            contextual_chunks.append(r)
        elif isinstance(r, Exception):
            logger.warning(f"上下文生成异常: {r}")

    contextual_chunks.sort(key=lambda c: c.chunk_index)

    prefixed_count = sum(1 for c in contextual_chunks if c.context_prefix)
    logger.info(
        f"Contextual 分块: {len(raw_chunks)} 块, "
        f"{prefixed_count}/{len(contextual_chunks)} 块成功添加上下文前缀"
    )

    return contextual_chunks
