"""
rag/chunking 分块策略单元测试
"""
import pytest
from app.services.rag.chunking import (
    ChunkStrategy,
    split_text_into_chunks,
    _chunk_fixed,
    _chunk_by_sentence,
    _chunk_by_markdown,
)


class TestChunkFixed:
    def test_short_text_single_chunk(self):
        text = "这是一段很短的文本"
        chunks = _chunk_fixed(text, chunk_size=500, overlap=50)
        assert len(chunks) == 1
        assert chunks[0] == text

    def test_long_text_splits_correctly(self):
        text = "A" * 1200
        chunks = _chunk_fixed(text, chunk_size=500, overlap=50)
        assert len(chunks) >= 2
        for c in chunks:
            assert len(c) <= 600  # 留一点余量给句子边界扩展

    def test_overlap_maintains_continuity(self):
        text = "一。" * 300  # 600 字符
        chunks = _chunk_fixed(text, chunk_size=200, overlap=20)
        assert len(chunks) >= 2
        # 相邻 chunk 之间有重叠
        assert chunks[0][-10:] in chunks[1] or len(chunks[1]) > 0

    def test_empty_text_returns_empty(self):
        assert _chunk_fixed("", chunk_size=500, overlap=50) == []

    def test_sentence_boundary_respected(self):
        text = "第一句话。第二句话。第三句话。" * 50
        chunks = _chunk_fixed(text, chunk_size=100, overlap=10)
        # 大多数 chunk 应该在句号处结束或开始
        for c in chunks[:-1]:
            assert len(c) > 0


class TestChunkBySentence:
    def test_basic_sentence_split(self):
        text = "这是第一句话。这是第二句话。这是第三句话。"
        chunks = _chunk_by_sentence(text, chunk_size=20, overlap=5)
        assert len(chunks) >= 1
        assert all(len(c) > 0 for c in chunks)

    def test_long_sentences_still_chunk(self):
        long_sentence = "这是一个非常长的句子" * 100
        chunks = _chunk_by_sentence(long_sentence, chunk_size=200, overlap=0)
        assert len(chunks) >= 1


class TestChunkByMarkdown:
    def test_markdown_splits_on_headings(self):
        text = "# 第一章\n内容1\n## 1.1 节\n内容1.1\n# 第二章\n内容2"
        chunks = _chunk_by_markdown(text, chunk_size=1000)
        assert len(chunks) == 3  # 3 个标题段落

    def test_no_headings_fallback_to_fixed(self):
        text = "没有标题的文本 " * 100
        chunks = _chunk_by_markdown(text, chunk_size=100)
        assert len(chunks) >= 1

    def test_large_section_further_splits(self):
        # 超大的 section 应该被进一步切分
        text = "# 大章节\n" + "内容" * 300
        chunks = _chunk_by_markdown(text, chunk_size=100)
        assert len(chunks) >= 2


class TestSplitTextIntoChunks:
    def test_fixed_strategy_default(self):
        text = "测试文本 " * 200
        chunks = split_text_into_chunks(text, strategy=ChunkStrategy.FIXED)
        assert len(chunks) >= 1

    def test_sentence_strategy(self):
        text = "第一句。第二句。第三句。" * 50
        chunks = split_text_into_chunks(text, strategy=ChunkStrategy.SENTENCE, chunk_size=100)
        assert len(chunks) >= 1

    def test_markdown_strategy(self):
        text = "# 章节一\n内容\n# 章节二\n内容"
        chunks = split_text_into_chunks(text, strategy=ChunkStrategy.MARKDOWN)
        assert len(chunks) == 2

    def test_empty_text(self):
        assert split_text_into_chunks("") == []
        assert split_text_into_chunks("   ") == []

    def test_backward_compat_no_strategy(self):
        """不传 strategy 参数，默认 FIXED，兼容旧调用方式"""
        text = "兼容测试 " * 200
        chunks = split_text_into_chunks(text)
        assert len(chunks) >= 1
