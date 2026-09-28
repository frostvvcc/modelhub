# -*- coding: utf-8 -*-
"""根据 results/experiment_results.json 重绘论文图6.1（chunk_size 调优）和图6.2（检索方式对比）。"""
import json
import os

import matplotlib
import matplotlib.pyplot as plt

matplotlib.rcParams["font.sans-serif"] = ["PingFang SC", "Hiragino Sans GB", "Arial Unicode MS"]
matplotlib.rcParams["axes.unicode_minus"] = False

HERE = os.path.dirname(os.path.abspath(__file__))
R = json.load(open(os.path.join(HERE, "results", "experiment_results.json")))

# ---------- 图6.1 chunk_size 调优 ----------
sweep = R["E2_chunk_size_sweep"]
sizes = sorted(int(k) for k in sweep)
p3 = [sweep[str(s)]["Precision@3"] for s in sizes]
mrr = [sweep[str(s)]["MRR"] for s in sizes]

fig, ax = plt.subplots(figsize=(7.2, 4.2), dpi=200)
ax.plot(sizes, p3, "o-", color="#1f5fd0", linewidth=2, markersize=8, label="Precision@3")
ax.plot(sizes, mrr, "s--", color="#d62728", linewidth=2, markersize=8, label="MRR")
best = 600
ax.axvline(best, color="gray", linestyle=":", linewidth=1)
ax.annotate(f"综合最优: {best}", xy=(best, sweep[str(best)]["MRR"]),
            xytext=(best + 90, sweep[str(best)]["MRR"] + 0.012),
            color="#d62728", fontsize=11,
            arrowprops=dict(arrowstyle="->", color="#d62728"))
ax.set_xlabel("chunk_size（字符）", fontsize=12)
ax.set_ylabel("指标值", fontsize=12)
ax.set_xticks(sizes)
ax.margins(y=0.15)
ax.grid(alpha=0.3)
ax.legend(loc="center right", fontsize=11)
fig.tight_layout()
fig.savefig(os.path.join(HERE, "results", "fig6_1_chunk_sweep.png"))
print("fig6_1 已生成")

# ---------- 图6.2 检索方式对比 ----------
modes = ["vector", "bm25", "hybrid"]
names = ["向量检索", "BM25检索", "RRF混合检索"]
metrics = [("Precision@1", "#3b7ddd"), ("Precision@3", "#f0a30a"), ("MRR", "#13a26b")]
e3 = R["E3_retrieval_mode"]

fig, ax = plt.subplots(figsize=(7.6, 4.4), dpi=200)
width = 0.25
for j, (mk, color) in enumerate(metrics):
    vals = [e3[m][mk] for m in modes]
    xs = [i + (j - 1) * width for i in range(len(modes))]
    bars = ax.bar(xs, vals, width=width * 0.92, color=color, label=mk)
    for x, v in zip(xs, vals):
        ax.text(x, v + 0.008, f"{v:.2f}", ha="center", fontsize=10)
ax.set_xticks(range(len(modes)))
ax.set_xticklabels(names, fontsize=12)
ax.set_ylabel("指标值", fontsize=12)
ax.set_ylim(0.45, 1.08)
ax.grid(axis="y", alpha=0.3)
ax.legend(loc="upper left", fontsize=11)
fig.tight_layout()
fig.savefig(os.path.join(HERE, "results", "fig6_2_retrieval_modes.png"))
print("fig6_2 已生成")
