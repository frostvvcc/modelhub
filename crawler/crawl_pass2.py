#!/usr/bin/env python3
"""
第二轮补充爬取：修正第一轮中路径错误导致抓取为0的站点，
并用已发现的学院专属路径重新爬取所有学院。
复用 sdust_crawler 中的所有核心函数。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from sdust_crawler import (
    crawl_site, Progress, log, OUTPUT_DIR, COLLEGE_KNOWN_LISTS,
    crawl_list, fetch, extract_body, extract_title, save,
    _safe_name, _article_urls_from_html,
)
import re
import time
from urllib.parse import urljoin

# ─── 修正后的主要站点配置 ───

FIXED_MAIN_SITES = [
    {
        "name": "学校官网",
        "base_url": "https://www.sdust.edu.cn",
        "lists": [
            {"category": "招标公告", "path": "/index/zbgg.htm", "max_pages": 10},
        ],
    },
    {
        "name": "新闻网-要闻",
        "base_url": "https://news.sdust.edu.cn",
        "lists": [
            {"category": "要闻传真", "path": "/ywcz.htm", "max_pages": 15},
            {"category": "校园采风", "path": "/xyfc.htm", "max_pages": 8},
            {"category": "媒体看科大", "path": "/mtkkd.htm", "max_pages": 5},
            {"category": "艺苑撷英", "path": "/yyxy.htm", "max_pages": 3},
        ],
    },
    {
        "name": "研究生院",
        "base_url": "https://yjsy.sdust.edu.cn",
        "lists": [
            {"category": "通知公告", "path": "/index/tzgg.htm", "max_pages": 8},
        ],
    },
    {
        "name": "招生网",
        "base_url": "https://zs.sdust.edu.cn",
        "lists": [
            {"category": "招生计划", "path": "/zsjh.htm", "max_pages": 5},
            {"category": "招生问答", "path": "/zswd.htm", "max_pages": 5},
            {"category": "录取查询", "path": "/lqcx.htm", "max_pages": 3},
            {"category": "招生政策", "path": "/zszc.htm", "max_pages": 3},
        ],
    },
    {
        "name": "学生工作处",
        "base_url": "https://xsgzc.sdust.edu.cn",
        "lists": [
            {"category": "心理新闻", "path": "/xlyz/xwdt.htm", "max_pages": 5},
            {"category": "心理通知", "path": "/xlyz/tzgg.htm", "max_pages": 5},
            {"category": "国防通知", "path": "/gfjy/tzgg.htm", "max_pages": 3},
            {"category": "国防新闻", "path": "/gfjy/xwdt.htm", "max_pages": 5},
            {"category": "育人通知", "path": "/ygzx/tzgg.htm", "max_pages": 5},
            {"category": "资助动态", "path": "/ygzx/zzdt.htm", "max_pages": 5},
        ],
    },
    {
        "name": "创新创业学院",
        "base_url": "https://cxcy.sdust.edu.cn",
        "lists": [
            {"category": "研究动态", "path": "/jyjx1/yjdt.htm", "max_pages": 5},
            {"category": "通知公告", "path": "/index/tzgg.htm", "max_pages": 5},
        ],
    },
    {
        "name": "人文社科处",
        "base_url": "https://rwskc.sdust.edu.cn",
        "lists": [
            {"category": "通知公告", "path": "/tzgg.htm", "max_pages": 5},
        ],
    },
    {
        "name": "人事处",
        "base_url": "https://rsc.sdust.edu.cn",
        "lists": [
            {"category": "通知公告", "path": "/tzgg.htm", "max_pages": 5},
            {"category": "通知公告2", "path": "/index/tzgg.htm", "max_pages": 3},
        ],
    },
]

# ─── 新闻网单位动态页（每个部门/学院在新闻网的独立栏目）───

NEWS_DWDT = [
    ("新闻网-教务处", "dwdt/jwc.htm"),
    ("新闻网-计算机学院", "dwdt/jsjxy.htm"),
    ("新闻网-安全学院", "dwdt/aqxy.htm"),
    ("新闻网-测绘学院", "dwdt/chxy.htm"),
    ("新闻网-财经学院", "dwdt/cjxy.htm"),
    ("新闻网-材料学院", "dwdt/clxy.htm"),
    ("新闻网-储能学院", "dwdt/cnxy.htm"),
    ("新闻网-创新创业学院", "dwdt/cxcyxy.htm"),
    ("新闻网-地科学院", "dwdt/dkxy.htm"),
    ("新闻网-电信学院", "dwdt/dxxy.htm"),
    ("新闻网-化工学院", "dwdt/hgxy.htm"),
    ("新闻网-海洋学院", "dwdt/hyxy.htm"),
    ("新闻网-机电学院", "dwdt/jdxy.htm"),
    ("新闻网-经管学院", "dwdt/jgxy.htm"),
    ("新闻网-交通学院", "dwdt/jtxy.htm"),
    ("新闻网-继续教育学院", "dwdt/jxjyxy.htm"),
    ("新闻网-马克思主义学院", "dwdt/mkszy.htm"),
    ("新闻网-能源学院", "dwdt/nyxy.htm"),
    ("新闻网-数学学院", "dwdt/sxxy.htm"),
    ("新闻网-土建学院", "dwdt/tjxy.htm"),
    ("新闻网-体育学院", "dwdt/tyxy.htm"),
    ("新闻网-文法学院", "dwdt/wfxy.htm"),
    ("新闻网-外国语学院", "dwdt/wgyxy.htm"),
    ("新闻网-研究生院", "dwdt/yjsy.htm"),
    ("新闻网-艺术学院", "dwdt/ysxy.htm"),
    ("新闻网-自动化学院", "dwdt/zdhxy.htm"),
    ("新闻网-智能装备学院", "dwdt/znzbxy.htm"),
    ("新闻网-资源学院", "dwdt/zyxy.htm"),
    ("新闻网-科技处", "dwdt/kjc.htm"),
    ("新闻网-学生工作处", "dwdt/xsgzb.htm"),
    ("新闻网-人事处", "dwdt/rsc.htm"),
    ("新闻网-国际交流合作处", "dwdt/gjjlhzc.htm"),
    ("新闻网-图书馆", "dwdt/tsg.htm"),
    ("新闻网-宣传部", "dwdt/xcb.htm"),
    ("新闻网-济南校区", "dwdt/jnxq.htm"),
    ("新闻网-泰安校区", "dwdt/taxq.htm"),
]


def crawl_news_dwdt(prog: Progress):
    """爬取新闻网各单位动态页"""
    base = "https://news.sdust.edu.cn"
    for name, path in NEWS_DWDT:
        log.info("━" * 40)
        log.info("▶ %s", name)

        urls = crawl_list(base, f"/{path}", 5)
        new_urls = [u for u in urls if u not in prog.done]
        log.info("  发现 %d 链接, 新 %d", len(urls), len(new_urls))

        folder = OUTPUT_DIR / _safe_name(name) / "动态"
        saved = 0

        for url in new_urls:
            html = fetch(url)
            if not html:
                prog.record(url, name, "fail")
                continue
            title = extract_title(html)
            body = extract_body(html)
            if not body:
                prog.record(url, name, "skip")
                continue
            if not title:
                title = body[:40].replace("\n", " ")
            save(folder, title, body)
            prog.record(url, name, "saved")
            saved += 1

        s = prog.stats[name]
        log.info("  ✓ %s: 保存=%d 跳过=%d 失败=%d", name, s["saved"], s["skip"], s["fail"])
        prog.flush()


def crawl_colleges_pass2(prog: Progress):
    """用已知路径爬取第一轮跳过的学院"""
    for base_url, lists in COLLEGE_KNOWN_LISTS.items():
        # find college name
        from sdust_crawler import COLLEGES
        cname = next((n for n, u in COLLEGES if u == base_url), base_url)

        # skip if we already have significant data from pass 1
        existing = prog.stats.get(cname, {}).get("saved", 0)
        if existing > 10:
            log.info("跳过 %s (已有 %d 篇)", cname, existing)
            continue

        site = {"name": cname, "base_url": base_url, "lists": lists}
        try:
            crawl_site(site, prog)
        except Exception as e:
            log.error("学院出错 %s: %s", cname, e)
            prog.flush()


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    prog = Progress()
    t0 = time.time()

    log.info("=" * 60)
    log.info("第二轮补充爬取：修正路径 + 学院补充 + 新闻网单位动态")
    log.info("=" * 60)

    # 1. 修正后的主要站点
    log.info("\n[1/3] 主要站点（修正路径）")
    for site in FIXED_MAIN_SITES:
        try:
            crawl_site(site, prog)
        except Exception as e:
            log.error("站点出错 %s: %s", site["name"], e)
            prog.flush()

    # 2. 学院补充
    log.info("\n[2/3] 学院补充爬取")
    crawl_colleges_pass2(prog)

    # 3. 新闻网单位动态
    log.info("\n[3/3] 新闻网各单位动态")
    crawl_news_dwdt(prog)

    # 汇总
    elapsed = time.time() - t0
    log.info("=" * 60)
    log.info("第二轮完成! 用时 %.1f 分钟", elapsed / 60)
    log.info("=" * 60)

    total = {"saved": 0, "skip": 0, "fail": 0}
    for sname in sorted(prog.stats):
        s = prog.stats[sname]
        for k in total:
            total[k] += s[k]
        if s["saved"] > 0 or s["fail"] > 0:
            log.info("  %-28s 保存=%3d 跳过=%3d 失败=%3d", sname, s["saved"], s["skip"], s["fail"])
    log.info("  " + "-" * 56)
    log.info("  %-28s 保存=%3d 跳过=%3d 失败=%3d", "合计", total["saved"], total["skip"], total["fail"])

    import json
    summary = {
        "total": total,
        "elapsed_minutes": round(elapsed / 60, 1),
        "sites": {k: dict(v) for k, v in prog.stats.items()},
    }
    (OUTPUT_DIR / "crawl_summary_pass2.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2)
    )
    prog.flush()


if __name__ == "__main__":
    main()
