# -*- coding: utf-8 -*-
"""从 eval/backups 的 ChromaDB chunk 备份中重建完整文档，组装论文第6章实验语料。

- 基础数据集（corpus_base）：毕设/教务/学位/手册类文档（vector_db 8/9/10/12 中的非新闻文档）
- 噪声数据集（corpus_noise）：校园新闻、活动报道等（vector_db 8 中的新闻 + vector_db 11）
- 扩展数据集 = 基础 + 噪声

chunk 按 chunk_id 排序后做后缀-前缀重叠去重拼接（原切块 overlap=150）。
"""
import json
import glob
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
BACKUPS = os.path.join(HERE, "..", "backups")

# 新闻/活动类文档的标题特征（归入噪声集）
NOISE_PAT = re.compile(
    r"音乐会|合唱比赛|调研|思政|校友|献礼|青春|颁奖|讲坛|回信|嘱托|交响|要闻|"
    r"一周一品|向.地.而行|实践绘新篇|党工委|党员|理论学习|看望慰问|开学第一课|"
    r"满天星|访问济南校区|学生代表大会|安全责任书|沙龙|招聘|产学研|校史陈列馆"
)


def merge_chunks(chunks):
    """按顺序拼接 chunk，去除相邻 chunk 间的重叠区。"""
    doc = chunks[0]
    for nxt in chunks[1:]:
        best = 0
        # 在 0~400 字符范围内找最长的 doc 后缀 == nxt 前缀
        for k in range(min(len(doc), len(nxt), 400), 19, -1):
            if doc[-k:] == nxt[:k]:
                best = k
                break
        doc += nxt[best:]
    return doc


def load_db(db_id):
    files = sorted(glob.glob(os.path.join(BACKUPS, f"vector_db_{db_id}_backup_*.json")))
    d = json.load(open(files[-1], encoding="utf-8"))
    by_doc = {}
    for cid, text, meta in zip(d["ids"], d["documents"], d["metadatas"]):
        did = meta.get("document_id") or cid.split("_chunk_")[0]
        by_doc.setdefault(did, []).append((meta.get("chunk_id", 0), text, meta))
    docs = {}
    for did, items in by_doc.items():
        items.sort(key=lambda x: x[0])
        source = items[0][2].get("source", f"doc_{did}.txt")
        docs[source] = merge_chunks([t for _, t, _ in items])
    return docs


def clean_name(source):
    # 去掉爬虫哈希前缀 sdust_xxxxxxxxxx_
    name = re.sub(r"^sdust_[0-9a-f]{10}_", "", source)
    name = name.replace("/", "_")
    if not name.endswith(".txt"):
        name += ".txt"
    return name


def main():
    base, noise = {}, {}
    for db in (8, 9, 10, 12):
        for source, text in load_db(db).items():
            name = clean_name(source)
            target = noise if NOISE_PAT.search(name) else base
            if name not in target or len(text) > len(target[name]):
                target[name] = text
    for source, text in load_db(11).items():
        name = clean_name(source)
        if name not in base:  # 与基础集重名的不重复加入
            if name not in noise or len(text) > len(noise[name]):
                noise[name] = text

    for sub, docs in (("corpus_base", base), ("corpus_noise", noise)):
        outdir = os.path.join(HERE, sub)
        os.makedirs(outdir, exist_ok=True)
        for name, text in docs.items():
            with open(os.path.join(outdir, name), "w", encoding="utf-8") as f:
                f.write(text)
        total = sum(len(t) for t in docs.values())
        print(f"{sub}: {len(docs)} 篇, {total} 字符")


if __name__ == "__main__":
    main()
