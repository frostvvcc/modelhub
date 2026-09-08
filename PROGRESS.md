# PROGRESS — 经验教训沉淀

> 按 CLAUDE.md 规范记录：遇到什么问题、如何解决、以后如何避免，附 commit ID。

## 2026-09-08 RAG 短板集中修复

### 1. 陈旧单测导致基线红灯（061c2a9）
- **问题**：`test_simple_permission_service.py` / `test_bot_service.py` 还在引用早已删除的 `Visibility` 枚举和 `scope`/`visibility` 参数，单测基线自始不可运行（收集期 ImportError）。
- **解决**：按现行权限模型（组织/教学空间可见性、创建权限只看角色）重写受影响用例。
- **教训**：重构服务 API 时必须同步跑并修对应单测；收集期错误会掩盖整个测试文件，比单个失败更隐蔽。

### 2. CRAG 循环恢复（4a765cd）
- **问题**：旧版 CRAG 在生成之后做 grounding 验证、失败后重新生成，导致回答重复输出、验证结果随机（同输入 33%→0%→100%）、每请求多 15-30 秒，最终在 fc7af4f 被整体拆除，系统失去自纠错能力。
- **解决**：把质量评估移到**生成之前**（retrieve → grade → [transform_query → retrieve]* → synthesize）。评估默认用检索管线自身分数（确定性、零开销），纠错动作改为查询改写+重走混合检索；synthesize 全图只执行一次且流式。
- **教训**：CRAG 的正确挂载点是检索阶段而不是生成阶段——生成后纠错必然带来重复生成与高昂延迟；用非确定性 LLM 判定做控制流条件前，先想清楚有没有确定性信号可用。

### 3. 运行时监控接入 Prometheus（8f00d9e）
- **问题**：RAGMonitor 只有内存滑窗 + JSONL，无法被 Prometheus/Grafana 抓取，线上质量退化不可观测（审计 P2-4）。
- **解决**：新增 `prometheus_metrics.py` + `GET /metrics`，在 RAGMonitor.record、CRAG grade 节点、grounding 后置校验三处埋点；依赖缺失时降级 no-op。

### 4. Word 表格结构丢失（7b85a8e）
- **问题**：docx 表格被拍平成 `a | b` 文本并集中堆到文末，丢失表头语义与位置（PDF 侧此前已修，docx 被遗漏）。
- **解决**：按文档 body 原始顺序遍历段落/表格，表格转 Markdown（与 PDF 提取格式一致）。
- **教训**：同类问题要横向排查所有文件格式的解析路径，不要只修被点名的那一个。

### 环境备注
- 本机 `.git/worktrees` 只读、`.git/config` 被锁，无法创建 worktree，按 CLAUDE.md 回退规则直接在 main 分支工作。
- 本机无 pip/venv 模块，用项目内 `backend/.tools/uv` 建 `backend/.venv` 跑测试（`.venv/bin/python -m pytest tests/unit/`）。

### 5. 集成测试与现行 API 脱节 + 测试混跑陷阱（1e6c138 / 4ae879e / 9114acd）
- **问题**：登录改为 account（学号/工号）、Bot 删除 visibility、VectorDb 删除 scope 后，集成测试从未同步，14 failed + 5 errors；且 unit conftest 全局 mock aiosqlite/redis/chromadb，与集成测试同进程混跑会大面积报错。
- **解决**：按现行语义重写集成测试；TEST.md 明确两套测试必须分进程运行。
- **教训**：删字段/改鉴权语义时全仓 grep 测试引用；基于 sys.modules mock 的测试体系不要与真实依赖测试同进程混跑。
