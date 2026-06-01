"""
文本分块策略模块
支持 fixed（固定大小）、sentence（句子边界）、markdown（标题层级）三种策略
"""
import re
from enum import Enum
from typing import List
from app.utils.logger_config import get_logger

logger = get_logger(__name__)


class ChunkStrategy(str, Enum):
    FIXED = "fixed"         # 固定大小分块（默认，兼容现有数据）
    SENTENCE = "sentence"   # 按句子边界分块
    MARKDOWN = "markdown"   # 按 Markdown 标题层级分块


def split_text_into_chunks(
    text: str,
    strategy: ChunkStrategy = ChunkStrategy.FIXED,
    chunk_size: int = 800,
    overlap: int = 150,
) -> List[str]:
    """
    将文本分割成块。

    Args:
        text: 要分割的文本
        strategy: 分块策略
        chunk_size: 每块最大字符数（FIXED/SENTENCE 策略使用）
        overlap: 块之间的重叠字符数（FIXED 策略使用）

    Returns:
        文本块列表
    """
    if not text or not text.strip():
        return []

    text = text.strip()

    if strategy == ChunkStrategy.MARKDOWN:
        return _chunk_by_markdown(text, chunk_size)
    elif strategy == ChunkStrategy.SENTENCE:
        return _chunk_by_sentence(text, chunk_size, overlap)
    else:
        return _chunk_fixed(text, chunk_size, overlap)


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
