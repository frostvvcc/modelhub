# ModelHub RAG 剩余问题改善方案

> 基于 2026-06-03 全量代码审查。
>
> 原则：**不为快速落地而降低技术深度**。每个方案给到面试能深聊的程度。

---

## P0 — 技术深度问题（面试核心追问点）

### 1. 去重策略：从计数器升级到 MMR（Maximal Marginal Relevance）

**现状：** `retrieval.py:95-112` 按 `document_id` 只保留 1 个 chunk。

**为什么不能只改成"保留 N 个"：** 同一文档的相邻 chunk 内容高度重叠（因为有 overlap），保留 3 个可能拿到 3 个几乎一样的段落，浪费 context window。面试官一问"同文档多 chunk 怎么保证多样性"就露馅。

**正确方案：MMR（Maximal Marginal Relevance）**

MMR 是 1998 年 Carbonell & Goldstein 提出的经典算法，核心思想：每次选下一个结果时，同时考虑它与 query 的相关性和它与已选结果的差异性。

$$MMR = \arg\max_{d_i \in R \setminus S} \left[ \lambda \cdot Sim(d_i, q) - (1-\lambda) \cdot \max_{d_j \in S} Sim(d_i, d_j) \right]$$

```python
# retrieval.py — 替换 _dedup_by_document

def _mmr_diversify(
    results: List[RetrievalResult],
    n_results: int,
    lambda_param: float = 0.7,
) -> List[RetrievalResult]:
    """
    MMR 多样性重排：在相关性和多样性之间取平衡。
    lambda=1.0 等价于纯相关性排序；lambda=0.0 等价于最大多样性。
    """
    if len(results) <= n_results:
        return results

    # 用 chunk 文本的 n-gram 重叠度做轻量 similarity（避免再调 embedding API）
    def _jaccard(a: str, b: str, n: int = 3) -> float:
        ngrams_a = set(a[i:i+n] for i in range(len(a) - n + 1)) if len(a) >= n else {a}
        ngrams_b = set(b[i:i+n] for i in range(len(b) - n + 1)) if len(b) >= n else {b}
        intersection = ngrams_a & ngrams_b
        union = ngrams_a | ngrams_b
        return len(intersection) / len(union) if union else 0.0

    selected: List[RetrievalResult] = []
    candidates = list(results)

    # 第一个：直接选最高分
    selected.append(candidates.pop(0))

    while len(selected) < n_results and candidates:
        best_idx, best_mmr = -1, -float('inf')
        for i, cand in enumerate(candidates):
            relevance = cand.score
            max_sim_to_selected = max(
                _jaccard(cand.content, s.content) for s in selected
            )
            mmr_score = lambda_param * relevance - (1 - lambda_param) * max_sim_to_selected
            if mmr_score > best_mmr:
                best_mmr = mmr_score
                best_idx = i
        if best_idx >= 0:
            selected.append(candidates.pop(best_idx))
        else:
            break

    return selected
```

**面试加分点：**
- 能讲清 MMR 公式和 λ 参数的含义
- 用 n-gram Jaccard 避免了额外的 embedding 计算开销
- 可以和面试官讨论 λ 的调参（偏相关 vs 偏多样）

**改动范围：** `retrieval.py`（替换 1 个函数），调用处 `_dedup_by_document` 改为 `_mmr_diversify`

---

### 2. Reranker：Cross-Encoder 为主，LLM 为备

**现状：** `reranker.py` 用 `qwen-plus` LLM 评分，这本质上是 **Listwise LLM Reranking**——把所有候选拼成一个 prompt 让 LLM 打分。

**为什么不能把 Cross-Encoder 定位成"可选"：** 面试时说"我做了 reranker"，对方第一个问题就是"用的什么模型？Cross-Encoder 还是 LLM？"。如果回答"LLM-based，Cross-Encoder 是可选的"，等于说你的主方案是最贵最慢的那个。

**正确架构：三级 Reranker**

```
Level 1: RRF 粗排（已有，零开销）
Level 2: Cross-Encoder 精排（主选，本地推理 ~100ms）
Level 3: LLM Listwise 精排（高精度场景，API 调用 ~1s）
```

```python
# reranker.py — 完整重构

import os
import asyncio
import json
import logging
from typing import List, Optional
from functools import lru_cache

logger = logging.getLogger(__name__)

# Cross-Encoder 单例（模型只加载一次，约 500MB 显存 / 1GB 内存）
_cross_encoder = None
_ce_lock = asyncio.Lock()


async def _get_cross_encoder(model_name: str = None):
    global _cross_encoder
    if _cross_encoder is not None:
        return _cross_encoder

    async with _ce_lock:
        if _cross_encoder is not None:
            return _cross_encoder
        model_name = model_name or os.getenv("RAG_RERANK_MODEL", "BAAI/bge-reranker-v2-m3")
        try:
            from sentence_transformers import CrossEncoder
            _cross_encoder = await asyncio.to_thread(CrossEncoder, model_name)
            logger.info(f"Cross-Encoder 加载完成: {model_name}")
        except ImportError:
            logger.warning("sentence-transformers 未安装，Cross-Encoder 不可用")
            _cross_encoder = None
    return _cross_encoder


async def cross_encoder_rerank(
    query: str,
    candidates: List["RetrievalResult"],
    top_k: int = 5,
) -> List["RetrievalResult"]:
    """Cross-Encoder 精排：对 query-document pair 做交叉注意力评分"""
    model = await _get_cross_encoder()
    if model is None:
        return await llm_rerank(query, candidates, top_k)

    pairs = [(query, c.content) for c in candidates]  # 完整内容，不截断
    scores = await asyncio.to_thread(model.predict, pairs)

    scored = sorted(zip(scores, candidates), key=lambda x: x[0], reverse=True)
    reranked = []
    for score, result in scored[:top_k]:
        result.rerank_score = float(score)
        result.retrieval_method = "hybrid+cross_encoder"
        reranked.append(result)

    logger.info(
        f"Cross-Encoder rerank: {len(candidates)} → {len(reranked)}, "
        f"top={scored[0][0]:.4f}, cutoff={scored[min(top_k-1, len(scored)-1)][0]:.4f}"
    )
    return reranked


async def llm_rerank(
    query: str,
    candidates: List["RetrievalResult"],
    top_k: int = 5,
    model: str = None,
) -> List["RetrievalResult"]:
    """LLM Listwise 精排：高精度但高延迟（备用方案）"""
    # ... 保持现有 rerank() 的实现，改名为 llm_rerank ...


# 统一入口
RAG_RERANK_MODE = os.getenv("RAG_RERANK_MODE", "cross_encoder")

async def rerank(
    query: str,
    candidates: List["RetrievalResult"],
    top_k: int = 5,
) -> List["RetrievalResult"]:
    if len(candidates) <= top_k:
        return candidates

    if RAG_RERANK_MODE == "cross_encoder":
        return await cross_encoder_rerank(query, candidates, top_k)
    elif RAG_RERANK_MODE == "llm":
        return await llm_rerank(query, candidates, top_k)
    else:
        return candidates[:top_k]
```

**关键设计点：**
- Cross-Encoder 模型用 `asyncio.Lock` 做单例初始化，避免并发请求重复加载
- `predict(pairs)` 看**完整 chunk 内容**，不截断——这是 Cross-Encoder 比 LLM rerank 的核心优势
- 默认 `RAG_RERANK_MODE=cross_encoder`，LLM 是 fallback
- 依赖 `sentence-transformers` 未安装时自动降级到 LLM

**面试加分点：**
- 能讲清 Cross-Encoder vs Bi-Encoder 的区别（交叉注意力 vs 独立编码）
- 能解释为什么 Cross-Encoder 精度更高（query 和 doc 在同一个 transformer 里做 attention）
- 能讨论 bge-reranker-v2-m3 的选型理由（多语言、轻量、MTEB 榜单排名）

**改动范围：** `reranker.py`（重构）、`vector_service.py`（`_apply_global_rerank` 直接调 `rerank()` 统一入口，无需改）

---

### 3. 新增语义分块（Semantic Chunking）— 当前完全缺失

**现状：** 4 种策略（fixed、sentence、markdown、parent_child）全部基于规则，没有基于语义的分块。

**为什么必须有：** 面试问"chunk 怎么切最好"，你答"我有固定、句子、Markdown、父子四种策略"——面试官下一句必定是"有没有做 Semantic Chunking？"。这是 2024-2025 RAG 论文里的热点，LlamaIndex 和 LangChain 都有原生支持。

**原理：** 计算相邻句子的 embedding 余弦相似度，在相似度骤降处切分。相似度高 = 语义连续，相似度骤降 = 话题转换。

```python
# chunking.py — 新增

import numpy as np
from typing import List, Tuple


class ChunkStrategy(str, Enum):
    FIXED = "fixed"
    SENTENCE = "sentence"
    MARKDOWN = "markdown"
    PARENT_CHILD = "parent_child"
    SEMANTIC = "semantic"            # ← 新增


def split_semantic(
    text: str,
    embedding_fn,  # Callable[[str], List[float]]
    max_chunk_size: int = 1000,
    similarity_threshold: float = 0.5,
    min_sentences: int = 3,
) -> List[str]:
    """
    语义分块：在 embedding 余弦相似度骤降处切分。

    算法：
    1. 按句子切分文本
    2. 每个句子生成 embedding
    3. 计算相邻句子的余弦相似度
    4. 在相似度低于阈值处切分
    5. 合并过短的 chunk（< min_sentences 句）
    """
    sentence_endings = re.compile(r'(?<=[。！？.!?\n])\s*')
    sentences = [s.strip() for s in sentence_endings.split(text) if s.strip()]

    if len(sentences) <= min_sentences:
        return [text.strip()] if text.strip() else []

    # 批量生成 embedding（复用 EmbbedingModel 的批量接口）
    embeddings = embedding_fn(sentences)
    emb_array = np.array(embeddings)

    # 计算相邻句子的余弦相似度
    norms = np.linalg.norm(emb_array, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1, norms)
    normalized = emb_array / norms
    similarities = np.sum(normalized[:-1] * normalized[1:], axis=1)  # cosine sim

    # 在相似度骤降处切分
    split_points = [0]
    for i, sim in enumerate(similarities):
        if sim < similarity_threshold:
            split_points.append(i + 1)
    split_points.append(len(sentences))

    # 合并为 chunk，尊重 max_chunk_size
    chunks = []
    for start, end in zip(split_points[:-1], split_points[1:]):
        chunk_text = ''.join(sentences[start:end])
        if len(chunk_text) > max_chunk_size:
            # 超长 chunk 用固定策略二次切分
            chunks.extend(_chunk_fixed(chunk_text, max_chunk_size, 0))
        elif chunk_text.strip():
            chunks.append(chunk_text.strip())

    # 合并过短的 chunk
    merged = []
    buffer = ""
    for chunk in chunks:
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
        f"threshold={similarity_threshold}"
    )
    return merged
```

**入库集成（vector_service.py）：**

```python
if strategy == ChunkStrategy.SEMANTIC:
    chunks = split_semantic(
        text_content,
        embedding_fn=embedding_model._get_text_embeddings,  # 批量接口
        max_chunk_size=safe_chunk_size,
    )
```

**面试加分点：**
- 能画出相邻句子相似度曲线图，解释"骤降点"就是话题切换点
- 能讨论 threshold 的选择（0.3-0.7 根据文档类型调参）
- 能比较 semantic chunking vs fixed chunking 在不同文档类型上的 recall 差异

**改动范围：** `chunking.py`（新增 ~60 行函数 + Enum 值）、`vector_service.py`（入库分支 + 传入 embedding_fn）

---

### 4. Grounding 检测：从 avg_similarity 升级到 Claim-Level NLI 验证

**现状：** `chat_service.py:141-148` 只用 `avg_similarity` 映射四档。

**为什么不能放在 P3：** "怎么检测幻觉"是 RAG 面试的**必问题**。你回答"我用检索分数的平均值判断"——面试官会说"那 LLM 编造了一个检索分数很高的段落里没说过的事实，你的检测能发现吗？"。答案是不能。

**正确方案：Post-Generation Claim-Level Verification**

```
LLM 回复 → 拆成独立 claim 列表 → 每个 claim 对比 source → NLI 判断（entail/contradict/neutral）
```

```python
# 新增文件：app/services/rag/grounding.py

async def verify_grounding(
    answer: str,
    sources: List[Dict[str, str]],
    model: str = None,
) -> Dict[str, Any]:
    """
    Claim-Level Grounding 验证：
    1. 将 LLM 回答拆成独立的事实声明（claims）
    2. 对每个 claim，检查是否被 source 支撑

    返回：{
        "claims": [{"text": "...", "supported": True, "source_idx": 1}, ...],
        "grounded_ratio": 0.85,     # 有支撑的 claim 占比
        "unsupported_claims": [...], # 无支撑的 claims（可能是幻觉）
    }
    """
    from app.config import settings
    model = model or settings.rag_llm_model

    client = _get_llm_client()

    # Step 1: 从回答中提取事实声明
    claims = await _extract_claims(client, model, answer)
    if not claims:
        return {"claims": [], "grounded_ratio": 1.0, "unsupported_claims": []}

    # Step 2: 逐条验证
    source_texts = "\n\n".join(
        f"[来源{i+1}] {s.get('content', '')}"
        for i, s in enumerate(sources)
    )

    verified = await _verify_claims(client, model, claims, source_texts)

    supported = [c for c in verified if c["supported"]]
    unsupported = [c for c in verified if not c["supported"]]
    ratio = len(supported) / len(verified) if verified else 1.0

    return {
        "claims": verified,
        "grounded_ratio": round(ratio, 4),
        "unsupported_claims": unsupported,
    }


async def _extract_claims(client, model, answer: str) -> List[str]:
    """将回答拆成独立的事实声明"""
    prompt = (
        "将以下回答拆分成独立的事实声明（claims），每条 claim 是一个可以独立验证真伪的陈述。\n"
        "去掉连接词、过渡语、主观评价，只保留客观事实。\n"
        '输出 JSON 数组：["claim1", "claim2", ...]\n\n'
        f"回答：{answer[:2000]}"
    )
    resp = await client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=500, temperature=0.0,
    )
    raw = resp.choices[0].message.content.strip()
    start, end = raw.find("["), raw.rfind("]") + 1
    if start >= 0 and end > start:
        return [str(c).strip() for c in json.loads(raw[start:end]) if isinstance(c, str)]
    return []


async def _verify_claims(
    client, model, claims: List[str], source_texts: str
) -> List[Dict]:
    """逐条验证 claim 是否被 source 支撑（NLI 三分类）"""
    prompt = (
        "你是一个事实核查专家。对于每条声明（claim），判断它是否被以下来源文本支撑。\n\n"
        f"来源文本：\n{source_texts[:4000]}\n\n"
        "声明列表：\n"
        + "\n".join(f"{i+1}. {c}" for i, c in enumerate(claims))
        + "\n\n"
        "对每条声明判断：\n"
        "- supported：来源文本明确支持该声明\n"
        "- unsupported：来源文本中找不到支持该声明的依据\n"
        "- contradicted：来源文本与该声明矛盾\n\n"
        '输出 JSON 数组：[{"claim": "...", "verdict": "supported|unsupported|contradicted", '
        '"source_idx": 来源编号或null, "reason": "一句话理由"}, ...]'
    )
    resp = await client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=1000, temperature=0.0,
    )
    raw = resp.choices[0].message.content.strip()
    start, end = raw.find("["), raw.rfind("]") + 1
    if start >= 0 and end > start:
        results = json.loads(raw[start:end])
        return [
            {
                "text": r.get("claim", claims[i] if i < len(claims) else ""),
                "supported": r.get("verdict") == "supported",
                "verdict": r.get("verdict", "unknown"),
                "source_idx": r.get("source_idx"),
                "reason": r.get("reason", ""),
            }
            for i, r in enumerate(results)
        ]
    return [{"text": c, "supported": False, "verdict": "unknown"} for c in claims]
```

**接入 chat_service.py：**

```python
# chat_service.py — chat() 方法，LLM 回复后

if rag_result["used_knowledge_base"] and source_citations:
    from app.services.rag.grounding import verify_grounding
    grounding_result = await verify_grounding(content, source_citations)
    assistant_metadata["grounding"] = grounding_result
    grounded_ratio = grounding_result["grounded_ratio"]
    grounded_level = AsyncChatService._grounding_summary(grounded_ratio)

    # 如果有不支持的 claim，在回复末尾追加警告
    unsupported = grounding_result.get("unsupported_claims", [])
    if unsupported:
        warning = "\n\n⚠️ 以下内容未在知识库中找到明确依据：\n"
        for uc in unsupported[:3]:
            warning += f"- {uc['text']}\n"
        content += warning
```

**面试加分点：**
- 能讲清 claim extraction → NLI verification 的两步流程
- 能解释和 Ragas Faithfulness metric 的关系（原理一致，实现不同）
- 能讨论 NLI 三分类（entail/contradict/neutral）vs 二分类的区别
- 有不支持的 claim 时**主动标注告警**——这是生产系统的关键特性

**改动范围：** 新增 `grounding.py`（~100 行）、`chat_service.py`（接入 ~10 行）

---

### 5. BM25：从"超限降级"升级到 Elasticsearch 全文检索

**现状：** 内存 BM25，全量加载，大 KB 会 OOM。

**为什么不能只加上限然后降级：** "超过 2 万条就放弃 BM25"等于告诉面试官你的 hybrid 检索在大数据量下是假的。面试官会问"那你的混合检索不就只剩向量了？"。

**正确方案：接入 Elasticsearch 做真正的分布式全文检索**

```python
# 新增文件：app/services/rag/es_retrieval.py

import os
from typing import List, Optional
from elasticsearch import AsyncElasticsearch

ES_ENABLED = os.getenv("ES_ENABLED", "false").lower() in ("true", "1")
ES_URL = os.getenv("ES_URL", "http://localhost:9200")

_es_client: Optional[AsyncElasticsearch] = None


async def get_es_client() -> Optional[AsyncElasticsearch]:
    global _es_client
    if not ES_ENABLED:
        return None
    if _es_client is None:
        _es_client = AsyncElasticsearch(ES_URL)
    return _es_client


async def es_index_chunks(
    vector_db_id: int,
    chunks: List[dict],  # [{"chunk_id": "...", "content": "...", "metadata": {...}}]
) -> int:
    """入库时同步写入 Elasticsearch"""
    client = await get_es_client()
    if not client:
        return 0

    index_name = f"modelhub_kb_{vector_db_id}"

    if not await client.indices.exists(index=index_name):
        await client.indices.create(index=index_name, body={
            "settings": {
                "analysis": {
                    "analyzer": {
                        "ik_smart_analyzer": {"type": "custom", "tokenizer": "ik_smart"}
                    }
                }
            },
            "mappings": {
                "properties": {
                    "content": {"type": "text", "analyzer": "ik_smart_analyzer"},
                    "chunk_id": {"type": "keyword"},
                    "source": {"type": "keyword"},
                    "document_id": {"type": "keyword"},
                }
            }
        })

    operations = []
    for chunk in chunks:
        operations.append({"index": {"_index": index_name, "_id": chunk["chunk_id"]}})
        operations.append({
            "content": chunk["content"],
            "chunk_id": chunk["chunk_id"],
            "source": chunk.get("metadata", {}).get("source", ""),
            "document_id": chunk.get("metadata", {}).get("document_id", ""),
        })

    if operations:
        await client.bulk(body=operations, refresh=True)
    return len(chunks)


async def es_search(
    vector_db_id: int,
    query: str,
    n_results: int = 10,
) -> List[dict]:
    """Elasticsearch BM25 全文检索"""
    client = await get_es_client()
    if not client:
        return []

    index_name = f"modelhub_kb_{vector_db_id}"
    try:
        resp = await client.search(
            index=index_name,
            body={
                "query": {"match": {"content": {"query": query, "analyzer": "ik_smart"}}},
                "size": n_results,
            },
        )
        return [
            {
                "chunk_id": hit["_id"],
                "content": hit["_source"]["content"],
                "score": hit["_score"],
                "source": hit["_source"].get("source", ""),
                "document_id": hit["_source"].get("document_id", ""),
            }
            for hit in resp["hits"]["hits"]
        ]
    except Exception as e:
        logger.warning(f"Elasticsearch 检索失败: {e}")
        return []
```

**retrieval.py 集成：** `hybrid_query` 中用 `es_search` 替代内存 BM25（ES 可用时），不可用时 fallback 到现有内存 BM25。

**docker-compose.yml 新增：**

```yaml
elasticsearch:
  image: elasticsearch:8.15.0
  environment:
    - discovery.type=single-node
    - xpack.security.enabled=false
    - "ES_JAVA_OPTS=-Xms512m -Xmx512m"
  ports:
    - "9200:9200"
  volumes:
    - modelhub_es_data:/usr/share/elasticsearch/data
```

**面试加分点：**
- 能讲清内存 BM25 的局限（全量加载、单进程、无分布式）
- 能讨论 Elasticsearch 的 IK 分词器配置（中文全文检索的标准方案）
- 能解释为什么保留了内存 BM25 作为 fallback（轻量部署场景不需要 ES）

**改动范围：** 新增 `es_retrieval.py`（~100 行）、`retrieval.py`（`_bm25_query` 加 ES 优先分支）、`vector_service.py`（入库时同步写 ES）、`docker-compose.yml`（新增 ES 服务）

---

## P1 — 有技术深度的工程改善

### 6. Embedding 批量入库 + ChromaDB 批量写入

原方案只改了 embedding 批量，但 `collection.add()` 仍然是逐个调用。ChromaDB 原生支持批量 `add`。

```python
# vector_service.py — 完整的批量优化

all_embeddings = embedding_model._get_text_embeddings(chunks)

all_ids = [f"{document_id}_chunk_{i}" for i in range(len(chunks))]
all_metadatas = [_build_metadata(i, chunk, ...) for i, chunk in enumerate(chunks)]

# ChromaDB 原生批量写入（一次网络调用）
collection.add(
    embeddings=all_embeddings,
    documents=chunks,
    metadatas=all_metadatas,
    ids=all_ids,
)
```

**比原方案多优化了什么：** 不仅 embedding API 批量化，ChromaDB 写入也从 N 次网络调用变成 1 次。

---

### 7. Token-based Context Budget（不变，方案合理）

tiktoken 方案保持不变。

### 8. 模型名 / 凭据可配置 + 领域参数化（不变，方案合理）

环境变量方案保持不变。

### 9. Chunk metadata 加章节标题（不变，方案合理）

### 10. Agent 工具截断对齐（不变，方案合理）

---

## P2 — 工程健壮性

### 11. Embedding API 重试（不变，tenacity 方案合理）

### 12. 多 Worker 部署（不变，gunicorn 方案合理）

### 13. 删除死代码（不变）

---

## P3 — 长期演进

### 14. BM25 缓存 Redis 化（如果接了 Elasticsearch 则不需要）

### 15. 运行时 Prometheus 监控

### 16. Eval 脚本可独立运行

---

## 改善优先级总览（修正版）

| 优先级 | 编号 | 问题 | 技术深度 | 面试价值 |
|--------|------|------|----------|----------|
| **P0** | #1 | MMR 多样性去重（替代计数器） | ⭐⭐⭐⭐ | 经典 IR 算法 |
| **P0** | #2 | Cross-Encoder 为主 + LLM 备用 | ⭐⭐⭐⭐⭐ | Reranker 核心追问点 |
| **P0** | #3 | 语义分块（Semantic Chunking） | ⭐⭐⭐⭐⭐ | Chunking 核心追问点 |
| **P0** | #4 | Claim-Level Grounding 验证 | ⭐⭐⭐⭐⭐ | 幻觉检测核心追问点 |
| **P0** | #5 | Elasticsearch 替代内存 BM25 | ⭐⭐⭐⭐ | 工程能力展示 |
| **P1** | #6 | 批量 Embedding + 批量 ChromaDB | ⭐⭐⭐ | 性能优化基本功 |
| **P1** | #7 | Token-based context budget | ⭐⭐⭐ | LLM 工程基本功 |
| **P1** | #8 | 模型名/凭据/领域可配置 | ⭐⭐ | 可扩展性 |
| **P1** | #9 | Chunk metadata 章节标题 | ⭐⭐⭐ | Citation 质量 |
| **P1** | #10 | Agent 截断对齐 | ⭐⭐ | Agent 完整性 |
| **P2** | #11-13 | 重试 / 多 Worker / 删死代码 | ⭐⭐ | 工程规范 |
| **P3** | #14-16 | Redis / 监控 / Eval | ⭐⭐⭐ | 生产成熟度 |
