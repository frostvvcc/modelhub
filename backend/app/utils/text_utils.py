"""
文本处理工具
"""
from typing import List
import logging

logger = logging.getLogger(__name__)


def split_text_into_chunks(text: str, chunk_size: int = 500, overlap: int = 50) -> List[str]:
    """
    将文本分割成块

    Args:
        text: 要分割的文本
        chunk_size: 每个块的大小（字符数）
        overlap: 块之间的重叠大小

    Returns:
        文本块列表
    """
    if not text:
        return []

    # 清理文本
    text = text.strip()

    # 如果文本小于等于 chunk_size，直接返回
    if len(text) <= chunk_size:
        return [text]

    chunks = []
    start = 0

    while start < len(text):
        # 计算块的结束位置
        end = start + chunk_size

        # 如果不是最后一块，尝试在句子边界处分割
        if end < len(text):
            # 寻找最近的句号、问号、感叹号、换行符
            for delimiter in ['\n\n', '\n', '。', '！', '？', '.', '!', '?']:
                delimiter_pos = text.rfind(delimiter, start, end)
                if delimiter_pos != -1 and delimiter_pos > start + chunk_size // 2:
                    end = delimiter_pos + len(delimiter)
                    break

        # 提取文本块
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)

        # 移动到下一个块的开始位置（考虑重叠）
        start = end - overlap if end < len(text) else end

    logger.info(f"文本分割完成: 原始长度={len(text)}, 分割成 {len(chunks)} 个块")
    return chunks
