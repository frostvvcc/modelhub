# Modelhub RAG 系统深度审计报告

> 审计日期：2026-06-03
> **修复完成日期：2026-06-04**
> 审计范围：全量代码 + 评测数据 + 文档交叉验证
> 审计目标：面试技术深度是否经得起追问
>
> **修复状态：全部 13 项问题已修复（4 P0 + 5 P1 + 4 P2），涉及 17 个文件（10 修改 + 7 新建）**

---

## 一、已确认修复的问题（14 项）

| # | 问题 | 修复位置 | 验证方式 |
|---|------|----------|----------|
| 1 | HyDE 是死代码 | `rag/query_rewriter.py` 完整实现，`RAG_USE_HYDE` 环境变量控制 | 代码审查 |
| 2 | 多轮上下文丢失 | `condense_follow_up()` 将追问重写为独立查询 | 代码审查 |
| 3 | 没有增强检索 pipeline | `retrieval.py` → `enhanced_query()` 多阶段管线 | 代码审查 |
| 4 | 缺少 BM25 混合检索 | RRF 融合 + jieba 分词 + 停用词 + ES 后端 | 消融数据 |
| 5 | 缺少 Reranker | 三级架构：RRF → Cross-Encoder → LLM fallback | 代码审查 |
| 6 | Grounding 只是平均相似度 | `grounding.py` 实现 Claim-Level NLI 验证 | 代码审查 |
| 7 | 缺少 Parent-Child 分块 | `chunking.py` → `split_parent_child()` | 代码审查 |
| 8 | `eval()` 代码注入漏洞 | Calculator 改用 AST 白名单解析 | 代码审查 |
| 9 | Agent 假流式输出 | 改用 `stream=True` 逐 token 输出 | 代码审查 |
| 10 | langchain 虚假依赖 | 已从 requirements 移除 | 代码审查 |
| 11 | Tool 串行执行 | `asyncio.gather` 并行调用 | 代码审查 |
| 12 | 结果去重不足 | MMR 实现（Jaccard n-gram + `RAG_MMR_LAMBDA` 可配置） | 代码审查 |
| 13 | 没有评测体系 | 三层框架：chunk quality → retrieval → e2e LLM judge | 代码 + JSON 报告 |
| 14 | 没有消融实验 | alpha / rrf_k / n_results 三组消融，有 JSON 报告 | 数据验证 |

---

## 二、P0 — 面试直接被打穿的致命问题

### P0-1：Cross-Encoder 从未真正运行过（"幽灵依赖"）

**现象：**

```python
# reranker.py:38-42
from sentence_transformers import CrossEncoder
_cross_encoder = await asyncio.to_thread(CrossEncoder, model_name)
...
except ImportError:
    logger.warning("sentence-transformers 未安装，Cross-Encoder 不可用")
```

- `sentence-transformers` **不在 requirements-fastapi.txt 中**
- 测试 `conftest.py` 直接 `sys.modules['sentence_transformers'] = MagicMock()`
- **后果：生产中永远 fallback 到 LLM Reranker，Cross-Encoder 层形同虚设**

**面试追问致命点：**
> "Cross-Encoder 和 LLM Reranker 的 latency 对比数据？"
> "bge-reranker-v2-m3 的 MTEB 排名你了解吗？实际跑出来效果比 LLM 好多少？"

**修复方案：**

1. 将 `sentence-transformers` 加入 `requirements-fastapi.txt`
2. 实际加载 `BAAI/bge-reranker-v2-m3` 并跑通推理
3. 做 rerank 模式消融：off vs cross_encoder vs llm，记录 recall@5 + latency
4. 把对比数据写入消融报告

**工作量：2h**

---

### P0-2：Context Budget 仍是字符级，不是 Token 级

**现象：**

```python
# chat_service.py:105
budget = max(1000, min(int(max_context_chars or 4000), 20000))
```

字段名就叫 `max_context_chars`，按字符截断。

**问题本质：**
- 中文 1 字 ≈ 2 tokens，英文 1 word ≈ 1-2 tokens
- 字符级截断在中英混合场景下误差可达 2-3 倍
- `RAG剩余问题改善方案.md` 明确写了"用 tiktoken 做 token-based budgeting"，**但代码完全没改**

**面试追问致命点：**
> "你上下文预算怎么保证不超 LLM 的 context window？"
> "中英混合文档的 token 计数你怎么处理的？"

**修复方案：**

1. `_build_context_blocks` 中引入 `count_tokens()`（`agent/memory.py` 里已有 tiktoken 实现）
2. 将 `max_context_chars` 改为 `max_context_tokens`，默认值从 4000 chars 调整为 2000 tokens
3. 截断逻辑改为按 token 累加

**工作量：1h**

---

### P0-3：E2E 评测数据半数无效 + 存在严重幻觉穿透

**现象（来自 `e2e_report.json` 实测）：**

| 维度 | 均分 | 最低分 | 问题 |
|------|------|--------|------|
| faithfulness | 4.67 | 4 | 还行 |
| completeness | 4.47 | 3 | 还行 |
| **citation_quality** | **3.6** | **1** | **严重不足** |
| no_hallucination | 4.87 | **1** | **存在灾难案例** |

关键问题：

- **30 条 query 中 15 条解析失败**（`"error": "无法解析"`）—— LLM judge 输出格式不稳定，评测数据只有一半有效
- `no_hallucination = 1` 的案例：LLM 虚构了 "2025届" 通知、伪造 URL 和发布日期
- `citation_quality = 1` 的案例：引用了完全无关的来源，编号混乱

**说明 Grounding 验证模块在实际对话链路中没有有效拦截幻觉。**

**面试追问致命点：**
> "你的幻觉检测准确率多少？漏检率多少？"
> "评测只有 15 条有效数据，你怎么得出'效果好'的结论？"

**修复方案：**

1. E2E eval 的 LLM judge prompt 加 `response_format: json_object`（或正则提取兜底 + retry）
2. 扩充评测 query 到 50-100 条
3. 确认 grounding 模块在 chat_service 主链路中被调用（目前只在 e2e_eval 里调用？还是在生产链路里？）
4. 对 grounding 模块本身做准确率评测（标注 20 条 claim 的 ground truth）

**工作量：3h**

---

### P0-4：评测样本量无统计显著性

**现象：**

- Ablation 实验：**15 条 query**
- E2E 评测：**30 条（有效仅 15 条）**
- 没有置信区间、没有 p-value、没有 bootstrap

**问题本质：**

alpha=0.6 的 recall@5=0.9333 vs alpha=0.5 的 recall@5=0.8000，差异 0.1333。在 15 条样本下：
- 这相当于多对了 2 条
- 二项检验 p > 0.1，**不显著**

**面试追问致命点：**
> "recall 从 0.80 提升到 0.93，这个提升显著吗？15 条数据够吗？"

**修复方案：**

1. 扩充 dataset 到至少 50 条（用 `dataset_generator.py` 自动生成 + 人工校验 20 条）
2. 消融报告加 bootstrap 95% 置信区间（`numpy.random.choice` 重采样 1000 次）
3. 如果不做统计检验，至少在报告里标注样本量，不要给出"最优"的绝对结论

**工作量：2h**

---

## 三、P1 — 技术深度明显不足

### P1-1：缺少 NDCG 指标

**现状：** `eval/metrics.py` 只有 Hit Rate、Recall、MRR

**问题：** NDCG（Normalized Discounted Cumulative Gain）是 IR 领域评估排序质量的核心指标，任何做过信息检索的面试官都会问。

**修复：** 在 `metrics.py` 中加 `ndcg_at_k()`，消融报告同步输出

**工作量：30min**

---

### P1-2：Chunking 策略没有对比消融

**现状：** 有 5 种分块策略（Fixed / Sentence / Markdown / Parent-Child / Semantic），但没有任何对比数据

**问题：** 面试官问"为什么选 chunk_size=800？为什么用 Fixed 而不是 Semantic？"你只能说"经验值"

**修复：**

1. 用同一份评测数据集，跑 Fixed vs Semantic 的 recall@5 对比
2. 跑 chunk_size = 400 / 600 / 800 / 1200 的对比
3. 写入消融报告

**工作量：2h**

---

### P1-3：GraphRAG 有实现无评测

**现状：** `graph_rag.py` 实现了 Neo4j 三元组提取 + 子图查询，但没有任何效果数据

**问题：** 面试说"我做了 GraphRAG"但被追问"提升了多少？"时拿不出数据

**修复：**

1. 对比 20 条 query 的回答质量：有 GraphRAG 上下文 vs 无 GraphRAG
2. 用 e2e_eval 的 4 维度打分
3. 如果 GraphRAG 效果不明显，也是有价值的结论（可以讲 trade-off）

**工作量：2h**

---

### P1-4：Reranker 没有被 ablation 覆盖

**现状：** 消融测了 alpha / rrf_k / n_results，但没有测 rerank 对效果的影响

**问题：** 三级 Reranker 是最大技术亮点之一，却没有数据支撑"它确实有用"

**修复：**

1. 在 `ablation.py` 加一组实验：rerank_mode = off vs cross_encoder vs llm
2. 对比 recall@5 和 MRR@5

**工作量：1h**（前提是 P0-1 先修复，Cross-Encoder 能实际运行）

---

### P1-5：Grounding 模块自身没有评测

**现状：**
- `grounding.py` 做 Claim-Level NLI
- 但没有 Ground Truth 来验证：
  - 断言提取的准确率（是否拆对了？）
  - NLI 分类的 precision / recall（是否判对了？）
  - 漏检率（多少幻觉穿透了？）

**问题：** 从 E2E 结果看，严重幻觉仍然出现（no_hallucination=1 的案例），说明 grounding 模块效果存疑

**修复：**

1. 人工标注 20 条 claim 的 ground truth（supported / unsupported / contradicted）
2. 计算 grounding 模块的 precision 和 recall
3. 确认主链路调用位置（是只在 eval 里调还是生产也调？）

**工作量：2h**

---

## 四、P2 — 工程质量问题

### P2-1：Agent REFLECTING 状态是空壳

**现状：**

```python
# engine.py:237-238
if self.state_machine.can_transition(AgentState.REFLECTING):
    self.state_machine.transition(AgentState.REFLECTING, "分析工具返回结果")
```

状态机转到 REFLECTING，但**没有独立的反思 prompt**。它只改了状态标签，然后继续 ReAct 循环。

**真正的 Reflection 应该有：**
- 审查上一步工具结果是否充分
- 判断是否需要换策略或补充调用
- 独立的 system prompt 指导反思推理

**工作量：1h**

---

### P2-2：ES 后端只有代码没有部署验证

**现状：** `es_retrieval.py` 存在，但实际部署用的是内存 BM25

**问题：** docker-compose.yml 里没有 ES 服务，说"支持 ES 分布式检索"但没有规模化验证

**工作量：1h**（加 ES 到 docker-compose + 跑通基本功能验证）

---

### P2-3：PDF 表格提取丢失结构

**现状：** `document_parser.py` 用 pdfplumber 提取表格，但只是 `'|'.join(row)` 拼成文本

**问题：** 复杂表格（合并单元格、嵌套表头）会丢失语义

**工作量：2h**（改为 Markdown table 格式保留结构）

---

### P2-4：没有运行时 RAG 质量监控

**现状：** Agent 有 `trace.py`，但 RAG 检索阶段没有运行时指标

**缺少的监控维度：**
- 平均检索 latency per stage（vector / BM25 / rerank / grounding）
- reranker 排序变化率（rerank 后 top-1 是否和 rerank 前不同）
- grounding ratio 的滑动平均
- 低置信度回答占比

**工作量：2h**

---

## 五、修复优先级矩阵

| 优先级 | 修复项 | 工作量 | 面试加分 | 依赖关系 |
|--------|--------|--------|----------|----------|
| **P0** | Cross-Encoder 加入依赖并实际运行 | 2h | 极高 | 无 |
| **P0** | Context budget 改 token 级 | 1h | 高 | 无 |
| **P0** | E2E eval 修复输出格式 + 扩充到 50-100 条 | 3h | 高 | 无 |
| **P0** | 评测数据加置信区间 | 2h | 高 | 依赖上一条 |
| **P1** | 加 NDCG 指标 | 30min | 中高 | 无 |
| **P1** | Chunking 策略消融 | 2h | 高 | 无 |
| **P1** | GraphRAG A/B 对比 | 2h | 高 | 无 |
| **P1** | Reranker 消融 | 1h | 高 | 依赖 P0-1 |
| **P1** | Grounding 模块评测 | 2h | 中高 | 无 |
| **P2** | Agent REFLECTING 加真正反思 prompt | 1h | 中 | 无 |
| **P2** | ES 加入 docker-compose | 1h | 中 | 无 |
| **P2** | PDF 表格结构化 | 2h | 低 | 无 |
| **P2** | RAG 运行时监控 | 2h | 中 | 无 |

**总计修复工作量：约 21.5h（≈ 3 天集中开发）**

---

## 六、核心结论

**架构设计完整度：8/10** — Hybrid Search、三级 Reranker、Claim-Level Grounding、多策略 Chunking、GraphRAG，该有的组件都有。

**数据支撑完整度：3/10** — Cross-Encoder 没真正跑过、评测数据只有 15 条有效、GraphRAG 没对比、Context Budget 方案写了但没改代码。

**面试风险：** 面试官不会因为架构图完整就认可，他们会追问 **"数据呢？效果提升多少？latency 多少？"** — 目前这些问题答不上来。

**一句话总结：有架构无数据。补数据是第一优先级。**
