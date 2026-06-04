# ModelHub 技术栈深度评审与面试级拷打

> 评审日期：2026-06-04
> 评审方式：全量代码审计（后端 28,500+ LOC / 前端 20,000+ LOC / 总计 ~48,500 LOC）
> 评审立场：以技术面试官视角，客观评价每一项技术栈的真实落地程度

---

## 一、项目概览

ModelHub 是一个面向高校场景的 **AI 模型管理与智能问答平台**，包含：

- 后端：FastAPI + SQLAlchemy (async) + Celery + Redis
- 前端：Vue 3 + TypeScript + Element Plus + Pinia
- RAG 管线：文档解析 → 分块 → Embedding → 向量/BM25 混合检索 → Rerank → Grounding 验证
- Agent 系统：ReAct 循环 + 状态机 + Tool Calling + 记忆管理 + Trace
- 基础设施：Docker Compose 8 服务编排（MySQL / Redis / ChromaDB / Elasticsearch / Neo4j / Backend / Celery / Nginx）
- 评测体系：自建 Retrieval Metrics + LLM-as-Judge + RAGAS 框架 + Ablation 消融实验

**Git 历史：5 次提交。** 这说明代码是批量提交的，无法从 git 历史判断迭代过程。

---

## 二、可写入简历的技术栈清单

| 技术栈 | 项目中的落地方式 | 深度评级 |
|--------|-----------------|---------|
| **Python / FastAPI** | 后端主框架，async 全链路，中间件、依赖注入、异常层级 | **深** |
| **SQLAlchemy 2.0 (Async ORM)** | 异步会话管理、连接池调优、Alembic 迁移 | **深** |
| **Vue 3 + TypeScript** | Composition API、Pinia 状态管理、路由守卫、SSE 流式渲染 | **中** |
| **RAG 管线设计与实现** | 5 种分块策略 + 混合检索 (Vector+BM25) + RRF 融合 + Rerank + Grounding | **深** |
| **LLM 应用工程** | 多模型统一调用、连接池、并发信号量、Token 预算管理 | **深** |
| **ReAct Agent** | 自建引擎：状态机编排 + Tool Calling + 安全分级 + Trace | **中深** |
| **向量数据库 (ChromaDB / Milvus)** | Strategy 模式双后端、HNSW 索引调参、索引缓存 | **深** |
| **Elasticsearch** | BM25 检索、IK 中文分词、异步客户端、可选降级 | **中** |
| **Neo4j / GraphRAG** | 三元组抽取 → Cypher 查询 → 子图上下文注入 | **浅中** |
| **Redis** | 连接池 + 健康检测 + NoOp 降级、缓存装饰器、Celery Broker | **中深** |
| **Celery** | 异步文档处理、进度上报、acks_late 可靠投递 | **中** |
| **Docker / Docker Compose** | 8 服务编排、健康检查、卷持久化、多阶段构建 | **中** |
| **RBAC 权限系统** | 角色-权限-组织层级模型（但存在双系统并行问题） | **中** |
| **RAG 评测体系** | Hit Rate/MRR/NDCG + LLM-as-Judge + RAGAS + Bootstrap CI | **中深** |
| **SSE 流式传输** | 前后端完整链路：FastAPI StreamingResponse → 前端 ReadableStream 解析 | **中** |
| **文档解析** | PDF(4 级降级) / Word / Excel / PPT / OCR / Markdown，含网页去噪 | **中深** |
| **Prompt 工程** | 多轮 Query 改写、HyDE、系统提示模板引擎、Citation 重编号 | **中** |

---

## 三、面试官级逐项拷打

### 3.1 RAG 管线 — 这是你最强的牌

#### 你做对了什么

**分块策略：5 种策略，不是空壳。**
- Fixed（带智能分隔符检测，不会在句子中间截断）
- Sentence（CJK 感知正则，中文句号/问号/感叹号正确分割）
- Markdown（保留 `#` 层级结构）
- Parent-Child（子块用于精准匹配，父块用于 LLM 上下文 — 这是生产级模式）
- Semantic（相邻句子余弦相似度聚类，有阈值控制）

**混合检索 + RRF 融合：公式正确实现。**
```
RRF_score = alpha/(k + rank_vector) + (1-alpha)/(k + rank_bm25)
```
k=60，alpha 可配置。当某一路没有返回结果时有正确的降级处理。

**BM25：不是调库了事。**
- 自建 LRU 缓存（TTL 10 分钟，最多缓存 20 个知识库），文档更新时自动失效
- Jieba 中文分词 + 51 个中文停用词 + 27 个英文停用词
- Jieba 不可用时降级到字符 bigram（而不是报错崩溃）

**MMR 多样性去重：真实现了 Jaccard n-gram 相似度。** 不是简单的 top-k 截断。

**Rerank 三级架构：**
1. Cross-Encoder（bge-reranker-v2-m3，懒加载单例）
2. LLM Listwise（送 query + 候选片段给 LLM 打分 1-10）
3. 禁用模式

**Grounding 验证：Claim 级 NLI。**
- LLM 拆解回答为原子事实 → 逐条比对源文本 → supported/unsupported/contradicted
- 返回 grounded_ratio，低于阈值给用户警告
- 这不是简单的相似度阈值，而是真正的 faithfulness 验证

#### 面试官会追问什么

**Q: 你的 Parent-Child 分块和 LlamaIndex 的 Small-to-Big 有什么区别？你为什么自己实现而不直接用 LlamaIndex？**

真实情况：你的实现确实是自建的，child 嵌入用于检索，parent_content 存在 metadata 里用于 LLM 上下文。但代码中同时也引用了 LlamaIndex 的 VectorStoreIndex（vector_index_cache.py），说明你对 LlamaIndex 有了解但选择核心逻辑自建。这是一个可以展开讲的点。

**Q: Semantic Chunking 的余弦相似度阈值怎么定的？有做 ablation 吗？**

你的 eval/ 目录下有 ablation.py 和 chunk_eval.py，说明你确实做了消融实验。但要注意：面试时需要能说出具体数字（阈值是多少，不同阈值对 Recall/MRR 的影响）。

**Q: RRF 的 k=60 和 alpha 是怎么调的？**

如果你做了 ablation 实验，应该能回答。如果没有，这是一个弱点——参数来源不明。

**Q: Grounding 验证的 latency 有多高？生产环境能承受吗？**

每次验证需要 2 次 LLM 调用（拆解 + NLI），latency 至少 2-4 秒。你的代码里确实有 monitor.py 记录延迟，但没有看到异步/可选的降级策略（比如只在高风险回答时触发）。

#### 客观评分：8/10
RAG 是你项目的核心竞争力。不是调库包装，而是真正理解了检索-排序-验证的完整链路。扣分点：部分参数调优缺乏可追溯的实验数据；GraphRAG 只抽取前 50 个 chunk 的三元组（大文档覆盖不全）。

---

### 3.2 Agent 系统 — 有工程量，但不算深

#### 你做了什么

**ReAct 循环（engine.py, 375 行）：**
- 状态机：IDLE → PLANNING → TOOL_CALLING → REFLECTING → RESPONDING → DONE/ERROR
- 中间轮非流式（省 token），最终轮流式输出
- Tool 安全分级：SAFE（无限制）、SENSITIVE（需 RBAC）、DANGEROUS（需用户确认）
- 并行 Tool 执行（asyncio.gather）
- 反思 Prompt 注入（Tool 结果后追加"请检查是否需要继续"）

**5 个内置工具（tools.py, 374 行）：**
1. KnowledgeSearchTool — 封装向量检索
2. DatabaseQueryTool — 查组织/用户结构化数据
3. CalculatorTool — AST 安全数学求值（白名单运算符，防注入）
4. DateTimeTool — 时间计算
5. TopicAnalysisTool — 意图分类，推荐工具

**记忆管理（memory.py）：**
- Token 感知压缩：保留最近 N 条 → LLM 摘要旧消息 → 硬编码兜底
- tiktoken 可用则用，否则字符数/2 估算

**Trace 追踪（trace.py）：**
- Span 结构：name, type, input, output, latency_ms, tokens_used
- 自动追踪每轮 LLM 调用、Tool 执行、最终流式输出

#### 面试官会追问什么

**Q: 你的 Agent 和 LangChain Agent / AutoGPT 有什么本质区别？**

坦率说：你的 Agent 是一个标准的 ReAct 实现，和 LangChain 的 AgentExecutor 在原理上没有本质区别。区别在于你自建了状态机和 Trace 而不是依赖框架。面试时不要过度包装，可以说"参考了 ReAct 论文的标准流程，自建了状态管理和追踪层"。

**Q: 最多支持几轮 Tool Calling？有没有防止无限循环的机制？**

代码里确实有 `max_iterations` 限制（默认 10），这是好的。但没有看到 token 总量熔断（如果每轮都用满 4096，10 轮就是 40K token，成本不低）。

**Q: 状态机有什么实际作用？去掉它系统还能跑吗？**

老实说：能跑。状态机主要用于 UI 状态展示和调试日志，不是核心调度逻辑。面试时可以说"状态机保证了状态转换的合法性，同时驱动前端的 Agent 过程可视化"。

#### 客观评分：6.5/10
Agent 系统有完整的工程实现，但技术深度一般。状态机简单（5 个状态、固定转换表），Tool 只有 5 个且多数是包装层。Trace 和安全分级是加分项。如果面试官问到多 Agent 协作、Planning、长链推理等高级话题，这个系统回答不了。

---

### 3.3 后端工程 — 你最被低估的部分

#### 真正体现工程能力的细节

**连接池与资源管理：**
- Redis：50 连接，30 秒健康检测，socket 超时 5 秒，重试 on timeout，**不可用时自动降级到 NoOpRedisClient**（不会因为 Redis 挂了整个系统崩掉）
- 数据库：pool_size=10, max_overflow=20, pool_pre_ping=True（连接健康检测），recycle=300s
- ChromaDB：单例 + heartbeat 验证，还设置了 NO_PROXY 环境变量（解决 macOS 系统代理干扰 — 这是真实踩坑经验）
- LLM：asyncio.Semaphore 全局并发限制（默认 10），防止 API rate limit 被打爆

**异常处理体系：**
- 自定义异常层级：AppException → ValidationError/NotFoundError/UnauthorizedError/ForbiddenError/ConflictError
- 中间件层捕获：RequestValidationError、IntegrityError → 409、OperationalError → 503、DataError → 400
- 服务装饰器 @service_method：自动日志 + 异常转换 + 敏感字段过滤（password/token/api_key 不入日志）

**这些不是教程代码。** 连接池调参、NoOp 降级、代理绕过、敏感字段过滤 — 都是真实生产环境踩过坑才会写的代码。

#### 面试官会追问什么

**Q: 你的 async_llm_pool 用信号量限制并发，但如果某个请求一直不返回怎么办？**

你的 Celery 配置了 soft_time_limit=300 和 time_limit=600，但 LLM 调用本身没有超时控制。async_llm.py 里 AsyncOpenAI 的 timeout 依赖客户端默认值。这是一个真实的生产隐患。

**Q: 你说 Redis 降级到 NoOp，那缓存失效后所有请求都打到数据库，会不会引发雪崩？**

好问题。你的 NoOpRedisClient 确实能防止崩溃，但没有限流/熔断机制。如果 Redis 挂了，所有 BM25 缓存失效、所有 rate limiter 失效、所有 session 缓存失效，数据库压力会骤增。面试时可以说"这是一个已知的 trade-off，下一步可以加 circuit breaker"。

**Q: 你的 auth.py 里的权限装饰器为什么不用 FastAPI 的 Depends？**

确实。你的 `@require_permission()` 检查 kwargs 而不是用依赖注入，这是非惯用写法。面试时坦诚说"这是从 Flask 迁移过来的遗留模式，更好的做法是用 FastAPI Depends"。

#### 客观评分：7.5/10
后端工程能力扎实。连接池、降级、异常体系、装饰器组合 — 这些是中高级后端工程师的标配。扣分点：JwtUtil.py 和 auth.py 功能重复（迁移不彻底）；数据库 async_query() 函数是空壳；部分权限检查散落在 router 层而不是统一在 service 层。

---

### 3.4 权限系统 — 建了两套，用了一套

#### 问题所在

你构建了一个完整的 RBAC 系统：
- Role 表（system/school/college/department/class 层级）
- Permission 表（resource:action 编码，如 knowledge:read）
- UserRole 关联表（支持组织范围内角色分配）
- RolePermission 关联表

**但实际使用的是 SimplePermissionService（511 行）。** 这是一个单体类，硬编码了所有访问控制逻辑：
- 向量库可见性检查
- Bot 可见性检查
- 教学空间准入
- 组织成员判断

两套系统并行运行。这在面试中是一个需要坦诚面对的技术债。

#### 面试官会怎么问

**Q: 为什么建了完整的 RBAC 但不用？**

实话实说：时间压力。RBAC 模型设计完了，但把所有路由从硬编码迁移到声明式权限检查需要大量测试和重构。SimplePermissionService 是 pragmatic 的过渡方案。

**Q: Organization.path 用字符串 "1/2/5" 存层级，为什么不用递归 CTE 或 materialized path 专门的列？**

你的实现确实是字符串 split + int 转换。这在小规模下可以工作，但大规模下有性能和一致性风险（如果有人手动修改了 path 字符串）。

#### 客观评分：5.5/10
设计意识到位（RBAC 模型完整），但落地不彻底。面试时建议主动提出重构方案，而不是等面试官追问。

---

### 3.5 前端 — 能用，但不是亮点

#### 做了什么

- **Vue 3 Composition API** + TypeScript 全链路
- **SSE 流式解析**：ReadableStream + 手动 buffer 管理 + 多回调（onToken / onToolCall / onSources / onTrace）
- **Pinia 状态管理**：用户认证 + 权限持久化
- **路由守卫**：多级组织权限验证
- **25+ 个视图组件**，覆盖完整的管理/聊天/知识库/Bot 构建功能

#### 问题

**ChatView.vue：1272 行。BotChatView.vue：1337 行。** 这是巨型组件，包含消息渲染、文件上传、设置面板、Citation 弹出层、Agent 过程可视化、Trace 面板……全部在一个文件里。

**手动 render 节流：**
```javascript
let renderTimer = null
const triggerRender = () => {
  if (renderTimer) return
  renderTimer = setTimeout(() => {
    renderKey.value++  // 强制 Vue 重新渲染
    renderTimer = null
  }, 50)
}
```
这是一种粗暴的 hack，应该用 `@vueuse/useThrottle` 或 `lodash.debounce`。

**SSE 缺少重连机制：** 网络抖动直接断开，没有指数退避重试。

**没有前端测试。** 零测试覆盖。

#### 面试官会怎么问

**Q: ChatView 1200+ 行怎么维护？**

应该拆成 4-5 个子组件：MessageList、MessageInput、SettingsDrawer、CitationPopover、AgentTracePanel。面试时主动说你知道需要重构。

**Q: 你的流式渲染有性能问题吗？**

手动 renderKey++ 每 50ms 强制重渲染，如果消息量大（比如一次返回 2000 个 token），会导致 DOM 频繁更新。更好的做法是用虚拟列表或只更新最后一个消息节点。

#### 客观评分：5.5/10
功能完整，但代码质量一般。大组件、无测试、手动 hack。前端不是你的强项，简历中建议弱化前端描述，突出后端和 RAG。

---

### 3.6 评测体系 — 有诚意的加分项

#### 你做了什么

**多层评测架构：**
1. **Retrieval Metrics（runner.py + metrics.py）：** Hit Rate@K, Recall@K, MRR@K, NDCG@K — 这些是 IR 领域的标准指标，不是随便写的
2. **E2E Eval（e2e_eval.py）：** RAG 检索 → LLM 生成 → LLM-as-Judge 四维打分（faithfulness / completeness / citation_quality / no_hallucination）
3. **RAGAS 框架集成（ragas_eval.py）：** Context Precision + Faithfulness + Answer Relevancy
4. **Ablation 消融实验（ablation.py）：** 带 Bootstrap CI 的统计检验
5. **Component-level Eval：** 分块评测、Reranker 评测、Grounding 评测、GraphRAG 评测

**这在个人项目中相当罕见。** 大多数简历项目只有 demo，没有评测。你有完整的评测框架和实验数据。

#### 问题

**JSON 解析 bug：** e2e_eval.py 中的正则 `(\d)` 只能捕获单位数，`"faithfulness": 10` 会被解析为 1。应该是 `(\d+)`。

**数据集生成器（dataset_generator.py）内容不确定，** 如果是空文件就是断层。

**硬编码模型名 "qwen-plus"** 出现在 eval 脚本中，应该参数化。

#### 客观评分：7/10
评测体系的存在本身就是加分。框架设计合理，指标选择专业。扣分点：JSON 解析 bug、部分脚本硬编码、数据集管理不够清晰。

---

### 3.7 基础设施 — 合格的 DevOps 意识

#### Docker Compose 8 服务：
| 服务 | 镜像 | 用途 |
|------|------|------|
| MySQL 8.0 | 数据库 | 结构化数据存储 |
| Redis 7 | 缓存 + 消息队列 | 缓存 / Celery Broker |
| ChromaDB | 向量数据库 | 开发环境 Embedding 存储 |
| Elasticsearch 8.15 | 搜索引擎 | BM25 中文全文检索 |
| Neo4j 5 | 图数据库 | GraphRAG 知识图谱 |
| Backend (FastAPI) | 4 Gunicorn workers | 主 API 服务 |
| Celery Worker x2 | 异步任务 | 文档处理 |
| Frontend (Nginx) | SPA 托管 | 前端服务 |

健康检查、依赖编排、卷持久化、多阶段构建（前端）都有。

**Celery 任务设计（document_tasks.py）：**
- 进度上报（0% → 20% → 30% → 90% → 100%）
- acks_late 保证可靠投递
- 重试 3 次，延迟 10 秒

#### 问题

**Embedding 没有批量调用：** 每个 chunk 单独调用一次 embedding API。100 个 chunk = 100 次 API 调用。如果用 batch API，1-2 次搞定。这是一个**严重的性能问题**。

**后端 Dockerfile 不是多阶段构建，** 镜像体积大（尤其 OCR 依赖约 500MB）。

#### 客观评分：6.5/10
能跑、能部署，但不算精细。面试时可以展开讲架构选型（为什么 ChromaDB 开发 + Milvus 生产），但要准备好回答 embedding 批量调用的问题。

---

## 四、总体评价与建议

### 综合评分

| 维度 | 评分 | 说明 |
|------|------|------|
| RAG 管线 | **8/10** | 真实现、有深度、有评测 |
| 后端工程 | **7.5/10** | 连接池/降级/异常体系扎实 |
| 评测体系 | **7/10** | 罕见的加分项 |
| Agent 系统 | **6.5/10** | 完整但不深，标准 ReAct |
| 基础设施 | **6.5/10** | 合格，有改进空间 |
| 权限系统 | **5.5/10** | 设计到位但落地不彻底 |
| 前端工程 | **5.5/10** | 功能完整但代码质量一般 |
| **综合** | **6.7/10** | **中上水平的个人项目** |

### 你的核心竞争力

1. **RAG 不是调库包装** — 你的检索、排序、验证是自建的，能讲清每一步的原理和 trade-off
2. **工程意识强** — 降级策略、连接池、异常层级、敏感字段过滤，这些是生产环境的思维
3. **有评测习惯** — 做了 ablation、用了 RAGAS、写了指标函数，说明你知道"不能只 demo，要量化"
4. **全栈覆盖** — 从 Docker 到前端到 AI，独立完成整个系统

### 你的短板（面试前必须准备答案）

1. **权限系统双轨并行** — 必须坦诚承认，并给出重构方案
2. **前端巨型组件** — ChatView 1200+ 行需要解释为什么没拆、怎么拆
3. **Embedding 没有批量调用** — 这是性能层面最大的问题，要说清楚你知道
4. **Git 历史只有 5 次提交** — 面试官可能质疑开发过程，要准备解释（比如"从内部仓库清理后重新提交"）
5. **Agent 深度有限** — 如果面试官问多 Agent 协作、Planning、长链推理，你的系统回答不了
6. **测试覆盖不足** — 后端单元测试覆盖约 40%，集成测试约 15%，前端零测试

### 面试策略建议

**主动引导到 RAG 管线** — 这是你最强的部分。如果面试官问"你在这个项目里做的最有挑战的事情是什么"，讲 RAG 混合检索 + Rerank + Grounding 的设计和调优。

**对弱点坦诚 + 给方案** — 面试官喜欢听到的不是"我做了 XXX"，而是"我做了 XXX，但我知道 YYY 是不够好的，下一步我会 ZZZ"。

**准备具体数据** — 你有 eval 系统，应该能说出：
- 混合检索比纯向量检索 Recall@5 提升了多少？
- Rerank 之后 MRR 变化了多少？
- Grounding 验证发现了多少幻觉比例？

**不要过度包装** — Agent 系统就是标准 ReAct，不要说"自研智能 Agent 框架"。GraphRAG 只抽取前 50 个 chunk，不要说"大规模知识图谱"。

---

## 五、技术栈 × 工程量矩阵

下表列出每个模块的实际代码行数，供面试准备参考：

| 模块 | 核心文件 | 行数 | 工程量评价 |
|------|---------|------|-----------|
| RAG 检索 | retrieval.py | 586 | 重度 |
| 向量服务 | vector_service.py | 1,884 | 重度 |
| 聊天服务 | chat_service.py | 1,130 | 重度 |
| 流式聊天 | stream_chat_service.py | 503 | 中度 |
| 文档解析 | document_parser.py | 502 | 中度 |
| Agent 引擎 | engine.py | 375 | 中度 |
| Agent Tools | tools.py | 374 | 中度 |
| 权限服务 | simple_permission_service.py | 511 | 中度 |
| 教学空间 | teaching_space_service.py | 693 | 中度 |
| 前端聊天 | ChatView.vue + BotChatView.vue | 2,609 | 重度（但需重构） |
| 评测框架 | eval/*.py (8 个文件) | ~1,500 | 中度 |
| 基础设施 | Docker + Celery + Scripts | ~500 | 轻度 |
| **总计** | | **~48,500** | |

---

## 六、一句话总结

> 这是一个**有真实工程深度的 RAG + Agent 平台**，不是套壳 demo。RAG 管线和后端工程是你的强项；Agent、前端、权限是你的弱项。面试时围绕 RAG 展开，对弱点诚实作答并给出改进方案，这个项目能撑住中高级后端/AI 工程师的面试。
