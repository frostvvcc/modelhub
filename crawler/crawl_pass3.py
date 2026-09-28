#!/usr/bin/env python3
"""
第三轮：专门抓取教务处通知公告（54页），同时处理 JSP 格式链接。
也补抓学校官网公告和新闻网单位动态中可能遗漏的 JSP 格式链接。
"""
import sys
import re
import time
import json
from pathlib import Path
from urllib.parse import urljoin, parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).parent))

from sdust_crawler import (
    fetch, extract_body, extract_title, save,
    _safe_name, Progress, log, OUTPUT_DIR,
    _article_urls_from_html as _original_article_urls,
)


def extract_all_article_urls(html: str, base_url: str) -> list[str]:
    """同时匹配 info/ 和 neirong.jsp 两种链接格式"""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "lxml")
    seen, urls = set(), []

    for a in soup.find_all("a", href=True):
        href = a["href"]

        # Format 1: info/XXXX/YYYY.htm (standard)
        if re.search(r"(?:^|/)info/\d+/\d+", href) and href.endswith(".htm"):
            full = urljoin(base_url, href)
            if full not in seen:
                seen.add(full)
                urls.append(full)
            continue

        # Format 2: neirong.jsp?...&wbtreeid=XXXX&wbnewsid=YYYY
        if "neirong.jsp" in href and "wbnewsid" in href:
            parsed = parse_qs(urlparse(href).query)
            tree_id = parsed.get("wbtreeid", [""])[0]
            news_id = parsed.get("wbnewsid", [""])[0]
            if tree_id and news_id:
                converted = urljoin(base_url, f"/info/{tree_id}/{news_id}.htm")
                if converted not in seen:
                    seen.add(converted)
                    urls.append(converted)

    return urls


def crawl_list_extended(base_url: str, list_path: str, max_pages: int) -> list[str]:
    """支持 JSP 链接格式的列表页爬取"""
    all_urls = []
    for page in range(max_pages):
        stem = list_path.rsplit(".htm", 1)[0]
        if page == 0:
            url = urljoin(base_url, list_path)
        else:
            url = urljoin(base_url, f"{stem}/{page}.htm")

        html = fetch(url)
        if not html:
            break
        urls = extract_all_article_urls(html, base_url)
        if not urls:
            break
        all_urls.extend(urls)

    return list(dict.fromkeys(all_urls))


TARGETS = [
    {
        "name": "教务处",
        "base_url": "https://jwc.sdust.edu.cn",
        "lists": [
            {"category": "通知公告", "path": "/tzgg.htm", "max_pages": 40},
        ],
    },
    {
        "name": "教务处",
        "base_url": "https://jwc.sdust.edu.cn",
        "lists": [
            {"category": "政策法规", "path": "/zcfg.htm", "max_pages": 5},
        ],
    },
]


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    prog = Progress()
    t0 = time.time()

    log.info("=" * 60)
    log.info("第三轮: 教务处通知公告（含JSP链接转换）")
    log.info("=" * 60)

    total_saved = 0
    for target in TARGETS:
        name = target["name"]
        base = target["base_url"]

        for lst in target["lists"]:
            cat = lst["category"]
            log.info("━" * 50)
            log.info("▶ %s / %s (最多%d页)", name, cat, lst["max_pages"])

            urls = crawl_list_extended(base, lst["path"], lst["max_pages"])
            new_urls = [u for u in urls if u not in prog.done]
            log.info("  发现 %d 链接, 新 %d", len(urls), len(new_urls))

            folder = OUTPUT_DIR / _safe_name(name) / _safe_name(cat)

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
                total_saved += 1

                if total_saved % 25 == 0:
                    prog.flush()

            s = prog.stats[name]
            log.info("  ✓ %s/%s: 保存=%d 跳过=%d 失败=%d", name, cat, s["saved"], s["skip"], s["fail"])

    elapsed = time.time() - t0
    log.info("=" * 60)
    log.info("第三轮完成! 用时 %.1f 分钟, 新增 %d 篇", elapsed / 60, total_saved)
    log.info("=" * 60)

    prog.flush()

    summary = {
        "pass3_new_articles": total_saved,
        "elapsed_minutes": round(elapsed / 60, 1),
    }
    (OUTPUT_DIR / "crawl_summary_pass3.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2)
    )


if __name__ == "__main__":
    main()
