# Model Hub RAG 检索系统不足分析

> 分析范围：`chunking.py`、`document_parser.py`、`retrieval.py`、`query_rewriter.py`、`reranker.py`、`chat_service.py`、`vector_service.py`、`stream_chat_service.py`、`agent/tools.py`、`EmbbedingModel.py` 共 10 个核心文件，逐行审查。
>
> 最后更新：2026-06-03

---

## 已解决的问题

### ~~1. HyDE 死代码~~ — ✅ 已修复

`hyde_rewrite()` 已通过 `vector_service.py:_prepare_enhanced_queries()` 接入主流程。由环境变量 `RAG_USE_HYDE` 控制开关（默认关闭），开启后在编排层全局执行一次，结果传递给所有 KB 的检索层。

### ~~2. 没有多轮对话上下文感知的 Query Reformulation~~ — ✅ 已修复

`chat_service.py:151-174` 实现了 `_reformulate_for_retrieval()`，在 RAG 检索前调用 `condense_follow_up()` 将追问补全为独立查询。`chat()`、`rechat()`、`bot_chat()` 三个入口全部接入。

### ~~增强检索管线未接入~~ — ✅ 已修复

完整的增强管线（Query Rewrite → HyDE → 多路 Hybrid → 全局 Rerank）已通过 `_prepare_enhanced_queries()` + `_apply_global_rerank()` 正确接入 `query_vector_by_model()`，全局最多 3 次 LLM 调用。

---

## 一、检索架构层面的硬伤（High Impact）

### 1. `_dedup_by_document` 过于激进 — 丢失多段相关内容

`retrieval.py:95-112`：同一文档只保留得分最高的一个 chunk。

```python
def _dedup_by_document(results: List[RetrievalResult]) -> List[RetrievalResult]:
    best: Dict[str, RetrievalResult] = {}
    for r in results:
        doc_key = r.document_id or r.chunk_id
        if doc_key not in best or r.score > best[doc_key].score:
            best[doc_key] = r  # 同一文档只保留最高分的 chunk
```

**问题场景**：《学生手册》有多个独立相关的段落（查重规则在第 3 章，截止日期在第 7 章），这个去重逻辑会把第二段直接丢掉。

**建议**：改为同一文档最多保留 N 个 chunk（如 2-3 个），或者只对相似内容去重（基于 chunk 文本相似度），而不是按 document_id 一刀切。

---

### 2. Reranker 只看了每个 chunk 的前 200 字符

`reranker.py:64`：

```python
content_preview = c.content[:200].replace('\n', ' ')
```

一个 800 字的 chunk，LLM reranker 只看前 200 字就打分。如果关键信息在 chunk 后半部分，会被错误地低分排序淘汰。

**建议**：
- 方案 A：传完整内容（注意 token 限制，可以按 candidates 数量动态调整截断长度）
- 方案 B：对超长 chunk 先做摘要再评分
- 方案 C：引入轻量级 Cross-Encoder 模型（如 `bge-reranker-v2`），速度更快且不需要截断

---

### 3. 缺少 Parent-Child Chunking（小块检索，大块回答）

当前的 chunking 策略是"切完就存"，检索到的 chunk 直接喂给 LLM。业界最佳实践是：

- 用**小 chunk**（200-400 字）做向量检索（精度高）
- 检索命中后，返回其所在的**大 chunk**（800-1200 字）给 LLM（上下文完整）

当前没有这种 small-to-big 的机制，导致要么检索精度低（chunk 太大），要么上下文不完整（chunk 太小）。

**建议**：在 `_process_and_add_file` 中同时生成 parent chunk 和 child chunk，child chunk 用于向量检索，命中后通过 metadata 中的 `parent_chunk_id` 查找 parent chunk 返回给 LLM。

---

### 4. Agent 知识检索工具也截断到 300 字

`agent/tools.py:92`：

```python
"content": (s.get("content") or "")[:300],
```

Agent 模式下的 `knowledge_search` 工具将检索结果截断到 300 字后喂给 ReAct 循环。Agent 拿到的上下文比直接 RAG 模式更少，决策质量更差。

**建议**：Agent 工具的截断阈值应至少和 chat_service 的 `max_context_chars` 对齐，或者直接传完整内容由 Agent 框架的 token budget 自行管理。

---

## 二、Chunking & 文档解析层面（Medium-High Impact）

### 5. PDF 表格没有结构化提取

`document_parser.py:198-206`：pdfplumber 支持 `page.extract_tables()`，但代码只调了 `page.extract_text()`。

```python
with pdfplumber.open(file_path) as pdf:
    for page in pdf.pages:
        text = page.extract_text()  # 只提取纯文本，表格结构丢失
```

注：Word 文档的表格提取已实现（`document_parser.py:176-179` 用 `doc.tables` 遍历），但 PDF 缺失。

**建议**：增加 `page.extract_tables()` 调用，将表格转为 Markdown 表格格式，作为独立的 chunk 存储。

---

### 6. Chunk 没有携带所属章节标题

`vector_service.py:373-407` 中 metadata 只有 `source`（文件名）、`chunk_id`、`document_id`：

```python
metadata = {
    'source': os.path.basename(actual_file_path),
    'chunk_id': i,
    'total_chunks': len(chunks),
    'document_id': document_id,
    'chunk_strategy': strategy.value,
    # 缺少：section_heading, page_number
}
```

**问题**：从《学生手册》里检索到一段文字，LLM 不知道这段来自"第三章 学业管理 > 3.2 论文查重"，citation 的可信度和可读性都差。

**建议**：在 chunking 阶段提取每个 chunk 所属的章节标题（通过正则匹配标题行或 Markdown heading），存入 metadata 的 `section_heading` 字段。PDF 文件还应记录 `page_number`。

---

### 7. Chunking 固定策略边界 Bug

`chunking.py:62-73` 的 `_chunk_fixed()` 中：

```python
while start < len(text):
    end = start + chunk_size
    if end < len(text):
        for delimiter in ['\n\n', '\n', '。', '！', '？', '.', '!', '?']:
            pos = text.rfind(delimiter, start, end)
            if pos != -1 and pos > start + chunk_size // 2:
                end = pos + len(delimiter)
                break
    chunk = text[start:end].strip()
```

**问题**：如果在 `[start + chunk_size//2, end]` 范围内找不到任何分隔符（比如一段超长的无标点英文），`end` 会保持 `start + chunk_size`，直接在字符中间硬截断。对于 `chunk_size=4000` 的配置，4000 字符的窗口内没有句号/换行的概率并不低（特别是代码块、URL 列表）。

**建议**：扩大搜索范围——如果首选范围找不到分隔符，向后扩展到 `chunk_size * 1.2` 找最近的分隔符，避免在语义中间断开。

---

## 三、工程可靠性问题（Medium Impact）

### 8. Embedding 是逐个 chunk 串行生成的

`vector_service.py:375`：

```python
for i, chunk in enumerate(chunks):
    embedding = embedding_model.get_text_embedding(chunk)  # 逐个调用
```

一个文件 50 个 chunk，就是 50 次串行 API 调用。而 `EmbbedingModel.py:64-77` 已经实现了 `_get_text_embeddings(texts)` 批量方法（每批 20 个），以及对应的异步版本 `_aget_text_embeddings()`。**批量接口已经写好了，但没用上。**

**建议**：将逐个调用改为批量调用，可以快 10-20 倍：

```python
embeddings = await embedding_model._aget_text_embeddings(chunks)
for i, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
    ...
```

---

### 9. BM25 全量加载内存 — 大知识库会 OOM

`retrieval.py:322-323`：

```python
data = await asyncio.to_thread(
    collection.get, include=['documents', 'metadatas']
)
```

把 ChromaDB 集合里的**所有文档**一次性加载到内存来构建 BM25 索引。如果知识库有 5 万个 chunk（每个 800 字），就是约 40MB 纯文本 + BM25 索引的内存开销。`_BM25_CACHE_MAX = 20` 意味着极端情况下占 800MB+。

**建议**：
- 短期：对大知识库限制 BM25 索引的 chunk 数量（如采样或只索引高频文档）
- 长期：用 Elasticsearch 或 MeiliSearch 替代内存 BM25

---

### 10. BM25 缓存不支持多 Worker 部署

`retrieval.py:37`：`_BM25_CACHE` 是进程内 `OrderedDict`。

- 如果用 gunicorn 起 4 个 worker，每个 worker 各自维护一份缓存，内存浪费 4 倍
- `invalidate_bm25_cache()` 只能失效当前 worker 的缓存，其他 worker 还在用旧数据
- `OrderedDict` 在 asyncio 并发下无锁保护，理论上存在竞态条件（虽然 CPython GIL 在大多数情况下保护了它）

**建议**：将 BM25 索引序列化后存入 Redis，或使用共享内存方案。

---

### 11. 上下文预算用字符数而不是 Token 数

`chat_service.py:105`：

```python
budget = max(1000, min(int(max_context_chars or 6000), 30000))
```

字符数和 token 数差异很大（中文约 1 字 = 1-2 token，英文约 4 字符 = 1 token）。`requirements.txt` 里已经装了 `tiktoken`，但没用上。这会导致要么浪费 context window，要么超出 token 限制被截断。

**建议**：将 `max_context_chars` 改为 `max_context_tokens`，用 tiktoken 计算实际 token 数。

---

### 12. Embedding API 调用无重试机制

`async_embedding.py:37-49` 和 `EmbbedingModel.py:52-57`：

embedding API 调用没有重试逻辑。对于阿里云 DashScope 这类云服务，瞬时网络抖动、限流（429）、服务端 5xx 都是常见场景。当前的行为是直接抛异常，导致整个文档入库失败。

**建议**：增加指数退避重试（如 tenacity 库），对 429/5xx 自动重试 3 次，对 4xx 直接失败。

---

## 四、可配置性和可扩展性（Low-Medium Impact）

### 13. Query Rewriter / Reranker 的模型名硬编码

```python
# query_rewriter.py:35, 96, 162
model: str = "qwen-plus"
# reranker.py:36
model: str = "qwen-plus"
```

4 处硬编码 `qwen-plus`，无法在不改代码的情况下切换模型。如果想用更便宜的模型做 rewrite、更强的模型做 rerank，必须改源码。

**建议**：从环境变量或 `model_config` 表中读取，如 `RAG_REWRITE_MODEL`、`RAG_RERANK_MODEL`。

---

### 14. Query Rewriter 和 HyDE 的 Prompt 硬编码了"大学"领域

```python
# query_rewriter.py:56
"用于在大学知识库中搜索相关文档"

# query_rewriter.py:183
"假设你是大学教务处的工作人员"
```

如果这个 Model Hub 想通用化（或面试时被问到可扩展性），这些 prompt 应该从 `model_config` 里读取，而不是写死。

---

### 15. Query Rewriter / Reranker 复用 Embedding 凭据调 Chat 接口

`query_rewriter.py:25-28` 和 `reranker.py:25-28`：

```python
_rewrite_client = AsyncOpenAI(
    api_key=settings.embedding_api_key,
    base_url=settings.embedding_base_url,
)
# 然后调用 client.chat.completions.create(model="qwen-plus", ...)
```

用 embedding 端点的凭据去调 chat completions 接口。当前阿里云 DashScope 兼容模式确实两者通用，但这是一个**隐式耦合**——如果将来 embedding 换成本地部署的 sentence-transformers（不支持 chat），rewrite 和 rerank 就会报 404。

**建议**：为 rewrite/rerank 配置独立的 LLM 凭据，如 `RAG_LLM_API_KEY` + `RAG_LLM_BASE_URL`，和 embedding 解耦。

---

### 16. vector_service.py 里有大量遗留的重复死代码

`vector_service.py:427-587`：`_extract_text_from_docx()` 和 `_extract_text_from_pdf()` 两个方法完全重复了 `document_parser.py` 的功能，且从未被调用（`_process_and_add_file` 调用的是 `document_parser.extract_text`）。

**建议**：直接删除这两个方法，减少维护负担和代码审查时的困惑。

---

## 五、可观测性和质量保障（Low-Medium Impact）

### 17. 没有 Retrieval 质量的运行时监控

`eval/` 目录下的评测框架是离线的。生产运行时没有采集：

- 检索延迟 P50/P95
- 各路（vector / BM25 / rerank）的命中率
- 用户对回答的满意度反馈（thumbs up/down）

无法知道线上 RAG 到底好不好用。

**建议**：在 `retrieval.py` 的关键路径埋点，将指标推送到 Prometheus/Grafana 或至少写入日志文件做定期分析。

---

### 18. "幻觉溯源"只是平均相似度，不是真正的 Grounding 检测

`chat_service.py:141-148`：

```python
def _grounding_summary(grounded_ratio: float) -> str:
    if grounded_ratio >= 0.75: return "高"
    elif grounded_ratio >= 0.55: return "中"
    elif grounded_ratio > 0: return "低"
    else: return "不足"
```

这只是把检索片段的平均相似度映射成"高/中/低"。**真正的 grounding 检测应该验证 LLM 回复中的每个事实主张是否能在检索片段中找到依据**，而不是看检索分数。

**建议**：增加 post-generation 的 grounding check——将 LLM 回答拆成 claim 列表，逐条检查是否被 source 支撑（如 Ragas 的 faithfulness metric 或 Vectara HHEM）。

---

### 19. Eval 评测脚本不可独立运行

`eval/runner.py:14` 直接 import `from app.services.rag.retrieval import VectorRetriever`，但脚本没有初始化 FastAPI 应用上下文（数据库连接、ChromaDB 客户端等）。

**问题**：运行 `python eval/runner.py` 会因为数据库未初始化而崩溃，必须手动配置环境后才能跑。

**建议**：增加 pytest fixture 或独立的环境初始化脚本，让评测可以一键运行。

---

## 六、建议优先级

| 优先级 | 编号 | 问题 | 改动量 | 面试加分 |
|--------|------|------|--------|----------|
| **P0** | #3 | Parent-child chunking | 中 | 极高 |
| **P0** | #1 | 放宽 document 去重策略 | 小 | 中 |
| **P1** | #2 | Reranker 全文评分 | 小 | 中 |
| **P1** | #8 | 批量 Embedding（接口已有） | 小 | 中 |
| **P1** | #5 | PDF 表格结构化提取 | 中 | 高 |
| **P1** | #6 | Chunk metadata 加章节标题 | 中 | 高 |
| **P2** | #4 | Agent 工具截断对齐 | 小 | 低 |
| **P2** | #7 | Chunking 边界 Bug | 小 | 低 |
| **P2** | #11 | Token-based context budget | 小 | 中 |
| **P2** | #12 | Embedding 重试机制 | 小 | 低 |
| **P2** | #13 | Rewrite/Rerank 模型可配置 | 小 | 中 |
| **P2** | #15 | Rewrite/Rerank 凭据解耦 | 小 | 中 |
| **P3** | #9 | BM25 分页加载 / 外部索引 | 大 | 中 |
| **P3** | #10 | BM25 缓存 Redis 化 | 大 | 中 |
| **P3** | #14 | Prompt 领域参数化 | 小 | 低 |
| **P3** | #16 | 删除死代码 | 小 | 低 |
| **P3** | #17 | 运行时质量监控 | 大 | 中 |
| **P3** | #18 | 真正的 grounding 检测 | 大 | 高 |
| **P3** | #19 | Eval 脚本可运行 | 中 | 低 |
