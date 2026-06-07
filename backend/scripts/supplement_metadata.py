"""
元数据补爬脚本

从已有的 crawler/output 目录结构中恢复院系和分类信息，
从原始 URL 页面中补爬发布日期。

产出：metadata_mapping.json，供文档入库时使用。

用法：
    # 仅从目录结构提取（不需要网络）
    python scripts/supplement_metadata.py --local-only

    # 完整模式：目录结构 + 网络补爬日期
    python scripts/supplement_metadata.py
"""
import argparse
import asyncio
import json
import os
import re
import sys
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
# Worktree 环境下 crawler/output 可能不存在，尝试找到原始项目目录
_ORIGINAL_ROOT = _PROJECT_ROOT
if ".claude/worktrees" in str(_PROJECT_ROOT):
    _ORIGINAL_ROOT = Path(str(_PROJECT_ROOT).split(".claude/worktrees")[0].rstrip("/"))

CRAWLER_OUTPUT = _ORIGINAL_ROOT / "crawler" / "output"
CRAWLER_PROGRESS = _ORIGINAL_ROOT / "crawler" / "crawl_progress.json"
OUTPUT_FILE = _PROJECT_ROOT / "backend" / "scripts" / "metadata_mapping.json"

# URL 子域名 → 院系名称映射
SUBDOMAIN_TO_DEPARTMENT = {
    "jwc": "教务处",
    "yjsy": "研究生院",
    "xgc": "学生工作处",
    "rsc": "人事处",
    "kjc": "科技处",
    "cxcy": "创新创业学院",
    "gjjl": "国际交流合作处",
    "tsg": "图书馆",
    "zs": "招生网",
    "wenfa": "文法学院",
    "waiyu": "外国语学院",
    "art": "艺术学院",
    "mks": "马克思主义学院",
    "math": "数学与系统科学学院",
    "cem": "材料科学与工程学院",
    "jdxy": "机械电子工程学院",
    "dqxy": "电气与自动化工程学院",
    "dzxy": "电子信息工程学院",
    "cse": "计算机科学与工程学院",
    "cgse": "测绘与空间信息学院",
    "dqkx": "地球科学与工程学院",
    "aqxy": "安全与环境工程学院",
    "tmgc": "土木工程与建筑学院",
    "jt": "交通学院",
    "hysw": "海洋科学与工程学院",
    "hxsw": "化学与生物工程学院",
    "jjgl": "经济管理学院",
    "cjxy": "财经学院",
    "cnxy": "储能技术学院",
    "ta": "智能装备学院",
    "znzb": "智能装备学院",
    "news": "新闻网",
    "www": "学校官网",
}

# 页面中提取发布日期的正则模式
DATE_PATTERNS = [
    re.compile(r'发布时间[：:]\s*(\d{4}[-/年.]\d{1,2}[-/月.]\d{1,2})'),
    re.compile(r'发布日期[：:]\s*(\d{4}[-/年.]\d{1,2}[-/月.]\d{1,2})'),
    re.compile(r'时间[：:]\s*(\d{4}[-/年.]\d{1,2}[-/月.]\d{1,2})'),
    re.compile(r'日期[：:]\s*(\d{4}[-/年.]\d{1,2}[-/月.]\d{1,2})'),
    re.compile(r'(\d{4}[-/年.]\d{1,2}[-/月.]\d{1,2})\s*(?:日?\s*)?(?:发布|来源|作者|浏览|点击)'),
    # HTML meta 或 class 中的日期
    re.compile(r'class="[^"]*(?:time|date|pubdate)[^"]*"[^>]*>\s*(\d{4}[-/年.]\d{1,2}[-/月.]\d{1,2})'),
    re.compile(r'<meta[^>]*(?:pubdate|publishdate|date)[^>]*content="(\d{4}[-/年.]\d{1,2}[-/月.]\d{1,2})'),
    # 最宽泛的 fallback：页面中靠前出现的日期
    re.compile(r'>\s*(\d{4}[-/]\d{1,2}[-/]\d{1,2})\s*<'),
]


def normalize_date(raw: str) -> str:
    """将各种日期格式统一为 YYYY-MM-DD"""
    raw = raw.replace("年", "-").replace("月", "-").replace("日", "").replace("/", "-").replace(".", "-")
    parts = raw.split("-")
    if len(parts) == 3:
        return f"{parts[0]}-{int(parts[1]):02d}-{int(parts[2]):02d}"
    return raw


def extract_department_from_url(url: str) -> str:
    """从 URL 子域名提取院系"""
    match = re.match(r'https?://(\w+)\.sdust\.edu\.cn', url)
    if match:
        subdomain = match.group(1)
        return SUBDOMAIN_TO_DEPARTMENT.get(subdomain, subdomain)
    return ""


def build_local_metadata() -> dict:
    """
    从 crawler/output 目录结构提取院系和分类信息。
    返回 {filename: {department, category}} 映射。
    """
    mapping = {}

    if not CRAWLER_OUTPUT.exists():
        print(f"[WARN] 爬虫输出目录不存在: {CRAWLER_OUTPUT}")
        return mapping

    for dept_dir in sorted(CRAWLER_OUTPUT.iterdir()):
        if not dept_dir.is_dir():
            continue
        department = dept_dir.name

        for cat_dir in sorted(dept_dir.iterdir()):
            if not cat_dir.is_dir():
                continue
            category = cat_dir.name

            for txt_file in cat_dir.glob("*.txt"):
                filename = txt_file.name
                key = f"{department}/{category}/{filename}"
                mapping[key] = {
                    "department": department,
                    "category": category,
                    "filename": filename,
                    "file_path": str(txt_file),
                }

    print(f"[INFO] 从目录结构提取: {len(mapping)} 个文件的元数据")
    return mapping


def load_crawled_urls() -> list:
    """从 crawl_progress.json 加载已爬取的 URL 列表"""
    if not CRAWLER_PROGRESS.exists():
        print(f"[WARN] 进度文件不存在: {CRAWLER_PROGRESS}")
        return []

    with open(CRAWLER_PROGRESS, "r") as f:
        data = json.load(f)

    urls = data.get("done", [])
    print(f"[INFO] 加载 {len(urls)} 个已爬取 URL")
    return urls


async def fetch_date_from_url(session, url: str, semaphore) -> tuple:
    """从单个 URL 页面提取发布日期"""
    async with semaphore:
        try:
            async with session.get(url, timeout=10) as resp:
                if resp.status != 200:
                    return url, None
                html = await resp.text(errors="replace")

                for pattern in DATE_PATTERNS:
                    match = pattern.search(html[:3000])
                    if match:
                        return url, normalize_date(match.group(1))

                return url, None
        except Exception:
            return url, None


async def supplement_dates(urls: list, local_mapping: dict) -> dict:
    """批量从 URL 补爬发布日期"""
    import aiohttp

    url_to_date = {}
    semaphore = asyncio.Semaphore(20)

    print(f"[INFO] 开始补爬 {len(urls)} 个页面的发布日期...")

    async with aiohttp.ClientSession(
        headers={"User-Agent": "Mozilla/5.0 (compatible; ModelhubBot/1.0)"},
        connector=aiohttp.TCPConnector(limit=20, ssl=False),
    ) as session:
        tasks = [fetch_date_from_url(session, url, semaphore) for url in urls]

        done_count = 0
        found_count = 0
        for coro in asyncio.as_completed(tasks):
            url, date = await coro
            done_count += 1
            if date:
                url_to_date[url] = date
                found_count += 1
            if done_count % 500 == 0:
                print(f"  进度: {done_count}/{len(urls)}, 已提取日期: {found_count}")

    print(f"[INFO] 日期补爬完成: {found_count}/{len(urls)} 个页面提取到日期")

    # 建立 URL → 院系+日期 的映射
    url_metadata = {}
    for url in urls:
        dept = extract_department_from_url(url)
        date = url_to_date.get(url)
        if dept or date:
            url_metadata[url] = {
                "department_from_url": dept,
                "publish_date": date,
            }

    return url_metadata


def merge_and_save(local_mapping: dict, url_metadata: dict):
    """合并本地元数据和 URL 元数据，保存到文件"""
    # 构建最终的元数据文件
    result = {
        "file_metadata": local_mapping,
        "url_metadata": url_metadata,
        "stats": {
            "total_files": len(local_mapping),
            "total_urls": len(url_metadata),
            "files_with_department": sum(1 for v in local_mapping.values() if v.get("department")),
            "urls_with_date": sum(1 for v in url_metadata.values() if v.get("publish_date")),
        },
    }

    OUTPUT_FILE.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"\n[DONE] 元数据已保存到: {OUTPUT_FILE}")
    print(f"  文件元数据: {result['stats']['total_files']} 条")
    print(f"  URL 元数据: {result['stats']['total_urls']} 条")
    print(f"  含院系信息: {result['stats']['files_with_department']} 条")
    print(f"  含发布日期: {result['stats']['urls_with_date']} 条")


def main():
    parser = argparse.ArgumentParser(description="元数据补爬脚本")
    parser.add_argument("--local-only", action="store_true", help="仅从目录结构提取，不联网补爬日期")
    args = parser.parse_args()

    # Step 1: 从目录结构提取院系和分类
    local_mapping = build_local_metadata()

    if args.local_only:
        merge_and_save(local_mapping, {})
        return

    # Step 2: 从 URL 补爬日期
    urls = load_crawled_urls()
    if not urls:
        print("[WARN] 无 URL 可补爬，仅保存本地元数据")
        merge_and_save(local_mapping, {})
        return

    url_metadata = asyncio.run(supplement_dates(urls, local_mapping))
    merge_and_save(local_mapping, url_metadata)


if __name__ == "__main__":
    main()
