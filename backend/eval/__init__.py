"""
ModelHub RAG 评测体系

三层评测：
  Layer 1: chunk_eval — 分块质量（LLM-as-Judge 语义完整度）
  Layer 2: runner + ablation — 检索质量（Hit Rate / Recall / MRR / NDCG + 消融 + Bootstrap CI）
  Layer 3: e2e_eval — 端到端回答质量（四维评分 + 重试 + 多策略 JSON 解析）

专项评测：
  reranker_eval — Reranker 模式消融（off / cross_encoder / llm）
  graphrag_eval — GraphRAG A/B 对比（有/无知识图谱上下文）
  grounding_eval — Grounding 模块准确率（标注数据 → Precision/Recall/F1）
"""
