# -*- coding: utf-8 -*-
"""论文第6章检索实验复现脚本。

实验内容：
  E1 切块策略对比（表6.3）：fixed / sentence / markdown，chunk_size=800，overlap=150，
     基础数据集 + 38题混合检索（α=0.7, k=60）
  E2 chunk_size 参数扫描（图6.1）：fixed 策略，chunk_size∈{200,400,600,800,1000,1200}，
     overlap=chunk_size×20%
  E3 检索方式对比（表6.4/图6.2）：扩展数据集，fixed@800/150，
     纯向量 / 纯BM25 / RRF混合，含按问题类型分组分析
  E4 α 灵敏度分析：扩展数据集，α∈{0.0,0.1,...,1.0}

指标定义（全文统一口径）：
  Precision@K = Top-K 检索结果中相关片段的比例（按题平均）
  Hit@K       = Top-K 中至少命中一个相关片段的比例
  MRR         = 首个相关片段排名倒数的均值（在 Top-10 内计算，Top-10 未命中计 0）
  相关性判定：片段来源文件名包含该题任一 expect_keywords 即为相关

切块逻辑使用项目 app/services/rag/chunking.py 的原始实现（仅替换 logger 导入）。
Embedding 使用 backend/.env 的 DashScope text-embedding-v3（1024 维），结果落盘缓存。

用法：python3 run_experiments.py  （在本目录运行）
"""
import hashlib
import json
import math
import os
import re
import sys
import time

import jieba
import numpy as np
from dotenv import load_dotenv
from openai import OpenAI
from rank_bm25 import BM25Okapi

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.abspath(os.path.join(HERE, "..", ".."))
load_dotenv(os.path.join(BACKEND, ".env"))

# ---------- 加载项目原始切块实现（仅替换 logger 导入） ----------
_src = open(os.path.join(BACKEND, "app/services/rag/chunking.py"), encoding="utf-8").read()
_src = _src.replace(
    "from app.utils.logger_config import get_logger",
    "import logging\n\ndef get_logger(name):\n    return logging.getLogger(name)",
)
chunking = type(sys)("chunking")
exec(compile(_src, "chunking.py", "exec"), chunking.__dict__)
ChunkStrategy = chunking.ChunkStrategy

# ---------- 加载项目原始文本清洗实现（论文流程中的"文本清洗"环节，同样仅替换 logger） ----------
_psrc = open(os.path.join(BACKEND, "app/services/rag/document_parser.py"), encoding="utf-8").read()
_psrc = _psrc.replace(
    "from app.utils.logger_config import get_logger",
    "import logging\n\ndef get_logger(name):\n    return logging.getLogger(name)",
)
# 只执行到清洗函数为止，避免引入解析器的重型依赖
_pend = _psrc.find("def extract_text")
parser_mod = type(sys)("parser_mod")
exec(compile(_psrc[:_pend if _pend > 0 else len(_psrc)], "document_parser.py", "exec"), parser_mod.__dict__)
clean_web_text = parser_mod.clean_web_text

# ---------- Embedding（带磁盘缓存） ----------
CACHE_PATH = os.path.join(HERE, "results", "emb_cache.json")
_cache = json.load(open(CACHE_PATH)) if os.path.exists(CACHE_PATH) else {}
_client = OpenAI(api_key=os.environ["EMBEDDING_API_KEY"], base_url=os.environ["EMBEDDING_BASE_URL"])
EMB_MODEL = os.environ.get("EMBEDDING_MODEL", "text-embedding-v3")


def embed(texts):
    keys = [hashlib.md5(t.encode()).hexdigest() for t in texts]
    missing = [(i, t) for i, (k, t) in enumerate(zip(keys, texts)) if k not in _cache]
    for s in range(0, len(missing), 10):  # 与系统实现一致：每批 10 条
        batch = missing[s:s + 10]
        resp = _client.embeddings.create(model=EMB_MODEL, input=[t for _, t in batch])
        for (i, t), d in zip(batch, resp.data):
            _cache[keys[i]] = d.embedding
        time.sleep(0.05)
    if missing:
        json.dump(_cache, open(CACHE_PATH, "w"))
    return np.array([_cache[k] for k in keys], dtype=np.float32)


# ---------- 语料与题集 ----------
def load_corpus(extended=False):
    docs = []
    dirs = [os.path.join(HERE, "corpus_base")]
    if extended:
        dirs.append(os.path.join(HERE, "corpus_noise"))
    for d in dirs:
        for name in sorted(os.listdir(d)):
            if name.endswith(".txt"):
                raw = open(os.path.join(d, name), encoding="utf-8").read()
                cleaned = clean_web_text(raw)
                # 清洗可能把短文档清空，兜底保留原文
                docs.append((name, cleaned if len(cleaned) >= 50 else raw))
    return docs


QUESTIONS = json.load(open(os.path.join(HERE, "questions_38.json")))["questions"]

_STOP = set("的了和与及或在是为对从被把等其该各类相关关于进行工作通知请按照？?，。、！!（）()　 \n\t")


def tokenize(text):
    return [w for w in jieba.lcut(text) if w.strip() and w not in _STOP]


# ---------- 索引与检索 ----------
class Index:
    def __init__(self, docs, strategy, chunk_size, overlap):
        self.chunks, self.sources = [], []
        for name, text in docs:
            for c in chunking.split_text_into_chunks(
                text, strategy=strategy, chunk_size=chunk_size, overlap=overlap
            ):
                self.chunks.append(c)
                self.sources.append(name)
        vecs = embed(self.chunks)
        self.vecs = vecs / np.linalg.norm(vecs, axis=1, keepdims=True)
        self.bm25 = BM25Okapi([tokenize(c) for c in self.chunks])

    def search_vector(self, qvec, k):
        sims = self.vecs @ (qvec / np.linalg.norm(qvec))
        order = np.argsort(-sims)[:k]
        return [(int(i), float(sims[i])) for i in order]

    def search_bm25(self, query, k):
        scores = self.bm25.get_scores(tokenize(query))
        order = np.argsort(-scores)[:k]
        return [(int(i), float(scores[i])) for i in order]

    def search_hybrid(self, query, qvec, k, alpha=0.7, rrf_k=60, pool=20):
        v = self.search_vector(qvec, pool)
        b = self.search_bm25(query, pool)
        score = {}
        for rank, (i, _) in enumerate(v, start=1):
            score[i] = score.get(i, 0) + alpha / (rrf_k + rank)
        for rank, (i, _) in enumerate(b, start=1):
            score[i] = score.get(i, 0) + (1 - alpha) / (rrf_k + rank)
        order = sorted(score, key=score.get, reverse=True)[:k]
        return [(i, score[i]) for i in order]


def evaluate(index, qvecs, mode="hybrid", alpha=0.7, topk=10):
    per_type = {}
    rows = []
    for q, qv in zip(QUESTIONS, qvecs):
        if mode == "vector":
            hits = index.search_vector(qv, topk)
        elif mode == "bm25":
            hits = index.search_bm25(q["query"], topk)
        else:
            hits = index.search_hybrid(q["query"], qv, topk, alpha=alpha)
        rel = [any(kw in index.sources[i] for kw in q["expect_keywords"]) for i, _ in hits]
        p1 = 1.0 if rel[:1] and rel[0] else 0.0
        p3 = sum(rel[:3]) / 3
        hit5 = 1.0 if any(rel[:5]) else 0.0
        rr = next((1.0 / (r + 1) for r, ok in enumerate(rel) if ok), 0.0)
        rows.append({"id": q["id"], "type": q["type"], "P@1": p1, "P@3": p3, "Hit@5": hit5, "RR": rr})
        per_type.setdefault(q["type"], []).append(rows[-1])
    agg = lambda rs, key: round(sum(r[key] for r in rs) / len(rs), 4)
    result = {k: agg(rows, k2) for k, k2 in
              [("Precision@1", "P@1"), ("Precision@3", "P@3"), ("Hit@5", "Hit@5"), ("MRR", "RR")]}
    result["by_type"] = {t: {"Precision@1": agg(rs, "P@1"), "Precision@3": agg(rs, "P@3"),
                             "Hit@5": agg(rs, "Hit@5"), "MRR": agg(rs, "RR"), "n": len(rs)}
                         for t, rs in per_type.items()}
    result["misses"] = [r["id"] for r in rows if r["RR"] == 0]
    return result


def main():
    os.makedirs(os.path.join(HERE, "results"), exist_ok=True)
    out = {}
    qvecs = embed([q["query"] for q in QUESTIONS])

    base = load_corpus(extended=False)
    ext = load_corpus(extended=True)
    print(f"基础数据集 {len(base)} 篇 / 扩展数据集 {len(ext)} 篇，问题 {len(QUESTIONS)} 题")

    # E1 切块策略对比
    out["E1_chunk_strategy"] = {}
    for strat in ["fixed", "sentence", "markdown"]:
        idx = Index(base, ChunkStrategy(strat), 800, 150)
        r = evaluate(idx, qvecs, mode="hybrid")
        r["chunks"] = len(idx.chunks)
        r["avg_len"] = round(sum(map(len, idx.chunks)) / len(idx.chunks), 1)
        out["E1_chunk_strategy"][strat] = r
        print(f"E1 {strat:9s} chunks={r['chunks']:4d} avg={r['avg_len']:6.1f} "
              f"P@3={r['Precision@3']} Hit@5={r['Hit@5']} MRR={r['MRR']} miss={r['misses']}")

    # E2 chunk_size 扫描
    out["E2_chunk_size_sweep"] = {}
    for size in [200, 400, 600, 800, 1000, 1200]:
        idx = Index(base, ChunkStrategy.FIXED, size, int(size * 0.2))
        r = evaluate(idx, qvecs, mode="hybrid")
        r["chunks"] = len(idx.chunks)
        out["E2_chunk_size_sweep"][size] = r
        print(f"E2 size={size:5d} chunks={r['chunks']:4d} P@3={r['Precision@3']} "
              f"Hit@5={r['Hit@5']} MRR={r['MRR']}")

    # E3 检索方式对比（扩展数据集）
    idx_ext = Index(ext, ChunkStrategy.FIXED, 800, 150)
    out["E3_retrieval_mode"] = {}
    for mode in ["vector", "bm25", "hybrid"]:
        r = evaluate(idx_ext, qvecs, mode=mode)
        out["E3_retrieval_mode"][mode] = r
        print(f"E3 {mode:7s} P@1={r['Precision@1']} P@3={r['Precision@3']} "
              f"Hit@5={r['Hit@5']} MRR={r['MRR']} miss={r['misses']}")

    # E4 α 灵敏度
    out["E4_alpha_sensitivity"] = {}
    for a in [round(x * 0.1, 1) for x in range(11)]:
        r = evaluate(idx_ext, qvecs, mode="hybrid", alpha=a)
        out["E4_alpha_sensitivity"][a] = {"MRR": r["MRR"], "Precision@3": r["Precision@3"]}
        print(f"E4 alpha={a} MRR={r['MRR']} P@3={r['Precision@3']}")

    out["meta"] = {
        "corpus_base_docs": len(base), "corpus_ext_docs": len(ext),
        "corpus_base_chars": sum(len(t) for _, t in base),
        "corpus_ext_chars": sum(len(t) for _, t in ext),
        "questions": len(QUESTIONS), "embedding_model": EMB_MODEL,
        "metric_note": "MRR 在 Top-10 内计算，未命中计 0；相关性=来源文件名含期望关键词",
    }
    json.dump(out, open(os.path.join(HERE, "results", "experiment_results.json"), "w"),
              ensure_ascii=False, indent=2)
    print("\n结果已写入 results/experiment_results.json")


if __name__ == "__main__":
    main()
