# Model Hub RAG 检索系统不足分析

> 分析范围：`chunking.py`、`document_parser.py`、`retrieval.py`、`query_rewriter.py`、`reranker.py`、`chat_service.py`、`vector_service.py` 共 7 个核心文件，逐行审查。

---

## 一、检索架构层面的硬伤（High Impact）

### 1. HyDE 写了但从没用过 — 死代码

`query_rewriter.py:93` 定义了 `hyde_rewrite()`，但在 `retrieval.py:445-448` 的 `enhanced_query` 里只调用了 `rewrite_query()`，HyDE 从头到尾没有被任何地方调用过。

```python
# retrieval.py:445-448 — 只用了 rewrite_query，没有 hyde_rewrite
if use_rewrite:
    from app.services.rag.query_rewriter import rewrite_query
    queries = await rewrite_query(query_text, n_rewrites=3)
```

**风险**：简历上如果写了 HyDE，面试追问实现细节会露馅。

**建议**：要么在 `enhanced_query` 中增加 `use_hyde` 参数并真正接入，要么删掉 `hyde_rewrite` 函数避免误导。

---

### 2. 没有多轮对话上下文感知的 Query Reformulation

`chat_service.py:460` 中 RAG 检索只用了当前用户消息 `message`：

```python
rag_result = await AsyncVectorService.query_vector_by_model(
    session, model_config_id, message, ...
)
```

**问题场景**：
- 用户第一条："毕设查重流程是什么？"
- 用户第二条："截止日期呢？"

第二条的 `message` 只有"截止日期呢？"，向量检索完全不知道在问毕设查重的截止日期。**这是生产环境里最常见的 RAG 失败场景。**

**建议**：在检索前增加一步 query reformulation，利用对话历史把追问补全成独立问题。例如用 LLM 将"截止日期呢？"改写为"毕业设计论文查重的截止日期是什么时候？"。

---

### 3. `_dedup_by_document` 过于激进 — 丢失多段相关内容

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

### 4. Reranker 只看了每个 chunk 的前 200 字符

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

## 二、Chunking & 文档解析层面（Medium-High Impact）

### 5. 缺少 Parent-Child Chunking（小块检索，大块回答）

当前的 chunking 策略是"切完就存"，检索到的 chunk 直接喂给 LLM。业界最佳实践是：

- 用**小 chunk**（200-400 字）做向量检索（精度高）
- 检索命中后，返回其所在的**大 chunk**（800-1200 字）给 LLM（上下文完整）

当前没有这种 small-to-big 的机制，导致要么检索精度低（chunk 太大），要么上下文不完整（chunk 太小）。

**建议**：在 `_process_and_add_file` 中同时生成 parent chunk 和 child chunk，child chunk 用于向量检索，命中后通过 metadata 中的 `parent_chunk_id` 查找 parent chunk 返回给 LLM。

---

### 6. PDF 表格没有结构化提取

`document_parser.py:198-206`：pdfplumber 支持 `page.extract_tables()`，但代码只调了 `page.extract_text()`。

```python
with pdfplumber.open(file_path) as pdf:
    for page in pdf.pages:
        text = page.extract_text()  # 只提取纯文本，表格结构丢失
```

大学通知里大量表格（课程安排、学分要求、缴费标准），纯文本提取后表格列全乱掉，检索到也无法正确理解。

**建议**：增加 `page.extract_tables()` 调用，将表格转为 Markdown 表格格式或保留管道分隔格式，作为独立的 chunk 存储。

---

### 7. Chunk 没有携带所属章节标题

`vector_service.py:381-389` 中 metadata 只有 `source`（文件名）、`chunk_id`、`document_id`：

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

## 三、工程可靠性问题（Medium Impact）

### 8. BM25 全量加载内存 — 大知识库会 OOM

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

### 9. BM25 缓存不支持多 Worker 部署

`retrieval.py:37`：`_BM25_CACHE` 是进程内 `OrderedDict`。

- 如果用 gunicorn 起 4 个 worker，每个 worker 各自维护一份缓存，内存浪费 4 倍
- `invalidate_bm25_cache()` 只能失效当前 worker 的缓存，其他 worker 还在用旧数据

**建议**：将 BM25 索引序列化后存入 Redis，或使用共享内存方案。

---

### 10. Embedding 是逐个 chunk 串行生成的

`vector_service.py:376-378`：

```python
for i, chunk in enumerate(chunks):
    embedding = embedding_model.get_text_embedding(chunk)  # 逐个调用
```

一个文件 50 个 chunk，就是 50 次串行 API 调用。大多数 embedding API（包括 DashScope）支持 batch input。

**建议**：改为 `embedding_model.get_text_embedding_batch(chunks)` 批量调用，可以快 10-20 倍。

---

### 11. 上下文预算用字符数而不是 Token 数

`chat_service.py:105`：

```python
budget = max(1000, min(int(max_context_chars or 6000), 30000))
```

字符数和 token 数差异很大（中文约 1 字 = 1-2 token，英文约 4 字符 = 1 token）。`requirements.txt` 里已经装了 `tiktoken`，但没用上。这会导致要么浪费 context window，要么超出 token 限制被截断。

**建议**：将 `max_context_chars` 改为 `max_context_tokens`，用 tiktoken 计算实际 token 数。

---

## 四、可优化项（Low-Medium Impact）

### 12. Query Rewriter 和 HyDE 的 Prompt 硬编码了"大学"领域

```python
# query_rewriter.py:56
"用于在大学知识库中搜索相关文档"

# query_rewriter.py:115
"假设你是大学教务处的工作人员"
```

如果这个 Model Hub 想通用化（或面试时被问到可扩展性），这些 prompt 应该从 `model_config` 里读取，而不是写死。

---

### 13. vector_service.py 里有大量遗留的重复死代码

`vector_service.py:430-537`：`_extract_text_from_docx()` 和 `_extract_text_from_pdf()` 两个方法完全重复了 `document_parser.py` 的功能，且从未被调用（`_process_and_add_file` 调用的是 `document_parser.extract_text`）。

**建议**：直接删除这两个方法，减少维护负担和代码审查时的困惑。

---

### 14. 没有 Retrieval 质量的运行时监控

`eval/` 目录下的评测框架是离线的。生产运行时没有采集：

- 检索延迟 P50/P95
- 各路（vector / BM25 / rerank）的命中率
- 用户对回答的满意度反馈（thumbs up/down）

无法知道线上 RAG 到底好不好用。

**建议**：在 `retrieval.py` 的关键路径埋点，将指标推送到 Prometheus/Grafana 或至少写入日志文件做定期分析。

---

### 15. "幻觉溯源"只是平均相似度，不是真正的 Grounding 检测

`chat_service.py:506-508`：

```python
grounded_level = AsyncChatService._grounding_summary(rag_result["avg_similarity"])
```

这只是把检索片段的平均相似度映射成"高/中/低"。**真正的 grounding 检测应该验证 LLM 回复中的每个事实主张是否能在检索片段中找到依据**，而不是看检索分数。

**建议**：增加 post-generation 的 grounding check——将 LLM 回答拆成 claim 列表，逐条检查是否被 source 支撑。

---

## 五、建议优先级

| 优先级 | 编号 | 问题 | 改动量 | 面试加分 |
|--------|------|------|--------|----------|
| **P0** | #2 | 多轮对话 query reformulation | 中 | 极高 |
| **P0** | #1 | 接入 HyDE 或删掉死代码 | 小 | 高 |
| **P1** | #5 | Parent-child chunking | 中 | 极高 |
| **P1** | #4 | Reranker 全文评分 | 小 | 中 |
| **P1** | #3 | 放宽 document 去重策略 | 小 | 中 |
| **P2** | #6 | PDF 表格结构化提取 | 中 | 高 |
| **P2** | #7 | Chunk metadata 加章节标题 | 中 | 高 |
| **P2** | #10 | Batch embedding | 小 | 中 |
| **P2** | #11 | Token-based context budget | 小 | 中 |
| **P3** | #8 | BM25 分页加载 / 外部索引 | 大 | 中 |
| **P3** | #9 | BM25 缓存 Redis 化 | 大 | 中 |
| **P3** | #14 | 运行时质量监控 | 大 | 中 |
| **P3** | #12 | Prompt 领域参数化 | 小 | 低 |
| **P3** | #13 | 删除死代码 | 小 | 低 |
| **P3** | #15 | 真正的 grounding 检测 | 大 | 高 |
