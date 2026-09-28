#!/usr/bin/env python3
"""
山东科技大学公开数据爬虫
从学校官网、教务处、新闻网、各学院等网站抓取公开的通知公告和新闻。
只提取正文内容，过滤导航、元数据等无关信息，输出干净的纯文本文件。
"""

import json
import logging
import re
import time
import unicodedata
from collections import defaultdict
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup, Comment

# ─────────────────── 配置 ───────────────────

BASE_DIR = Path(__file__).parent
OUTPUT_DIR = BASE_DIR / "output"
PROGRESS_FILE = BASE_DIR / "crawl_progress.json"

REQUEST_DELAY = 1.2
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36 "
    "SDUST-ModelHub-Collector/1.0"
)
REQUEST_TIMEOUT = 20
MAX_RETRIES = 2

CONTENT_SELECTORS = [
    "div.v_news_content",
    "div.wp_articlecontent",
    "div#vsb_content",
    "div.article_content",
    "div.news_content",
    "div.TRS_Editor",
    "div.entry-content",
    "div.col_news_con",
]

METADATA_RE = re.compile(
    r"^("
    r"来源[：:].{0,30}"
    r"|发布[人者]?[：:].{0,20}"
    r"|浏览次数[：:]\s*\d+"
    r"|发布时间[：:].{0,30}"
    r"|作者[：:].{0,20}"
    r"|审核[人者]?[：:].{0,20}"
    r"|点击数[：:]\s*\d+"
    r"|信息来源[：:].{0,30}"
    r"|编辑[：:].{0,20}"
    r"|录入[：:].{0,20}"
    r"|责任编辑[：:].{0,20}"
    r"|上一篇[：:].*"
    r"|下一篇[：:].*"
    r"|上一条[：:].*"
    r"|下一条[：:].*"
    r"|【关闭窗口】"
    r"|【打印本页】"
    r"|返回首页"
    r"|分享到.*"
    r")$",
    re.MULTILINE,
)

INLINE_META_RE = re.compile(
    r"[(（](?:供稿|摄影|责编|通讯员|记者|文[/／]图)[：:].{0,60}?[)）]"
)

GARBAGE_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f﻿​‌‍  ]")
MULTI_SPACES_RE = re.compile(r"[^\S\n]{2,}")
MULTI_NEWLINES_RE = re.compile(r"\n{3,}")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("crawler")

# ─────────────────── 目标站点定义 ───────────────────

MAIN_SITES = [
    {
        "name": "教务处",
        "base_url": "https://jwc.sdust.edu.cn",
        "lists": [
            {"category": "通知公告", "path": "/tzgg.htm", "max_pages": 20},
            {"category": "新闻动态", "path": "/xwdt.htm", "max_pages": 8},
        ],
    },
    {
        "name": "学校官网",
        "base_url": "https://www.sdust.edu.cn",
        "lists": [
            {"category": "科大公告", "path": "/kdgg.htm", "max_pages": 10},
        ],
    },
    {
        "name": "新闻网",
        "base_url": "https://news.sdust.edu.cn",
        "lists": [
            {"category": "要闻", "path": "/ywzx.htm", "max_pages": 10},
            {"category": "校园采风", "path": "/xycf.htm", "max_pages": 5},
            {"category": "媒体看科大", "path": "/mtkd.htm", "max_pages": 5},
        ],
    },
    {
        "name": "研究生院",
        "base_url": "https://yjsy.sdust.edu.cn",
        "lists": [
            {"category": "通知公告", "path": "/tzgg.htm", "max_pages": 8},
            {"category": "新闻动态", "path": "/xwdt.htm", "max_pages": 5},
        ],
    },
    {
        "name": "招生网",
        "base_url": "https://zs.sdust.edu.cn",
        "lists": [
            {"category": "招生公告", "path": "/tzgg.htm", "max_pages": 5},
            {"category": "招生动态", "path": "/zsdt.htm", "max_pages": 5},
        ],
    },
    {
        "name": "学生工作处",
        "base_url": "https://xsgzc.sdust.edu.cn",
        "lists": [
            {"category": "通知公告", "path": "/tzgg.htm", "max_pages": 8},
            {"category": "新闻动态", "path": "/xwdt.htm", "max_pages": 5},
        ],
    },
    {
        "name": "科技处",
        "base_url": "https://keyan.sdust.edu.cn",
        "lists": [
            {"category": "通知公告", "path": "/tzgg.htm", "max_pages": 5},
            {"category": "新闻动态", "path": "/xwdt.htm", "max_pages": 3},
        ],
    },
    {
        "name": "创新创业学院",
        "base_url": "https://cxcy.sdust.edu.cn",
        "lists": [
            {"category": "通知公告", "path": "/tzgg.htm", "max_pages": 5},
        ],
    },
    {
        "name": "人文社科处",
        "base_url": "https://rwskc.sdust.edu.cn",
        "lists": [
            {"category": "通知公告", "path": "/tzgg.htm", "max_pages": 3},
        ],
    },
    {
        "name": "国际交流合作处",
        "base_url": "https://fao.sdust.edu.cn",
        "lists": [
            {"category": "通知公告", "path": "/tzgg.htm", "max_pages": 3},
        ],
    },
    {
        "name": "人事处",
        "base_url": "https://rsc.sdust.edu.cn",
        "lists": [
            {"category": "通知公告", "path": "/tzgg.htm", "max_pages": 5},
        ],
    },
    {
        "name": "图书馆",
        "base_url": "https://sklib.sdust.edu.cn",
        "lists": [
            {"category": "通知公告", "path": "/tzgg.htm", "max_pages": 3},
        ],
    },
]

COLLEGES = [
    ("能源与矿业工程学院", "https://cms.sdust.edu.cn"),
    ("安全与环境工程学院", "https://csee.sdust.edu.cn"),
    ("测绘与空间信息学院", "https://gc.sdust.edu.cn"),
    ("地球科学与工程学院", "https://cgse.sdust.edu.cn"),
    ("土木工程与建筑学院", "https://fcea.sdust.edu.cn"),
    ("机械电子工程学院", "https://cmee.sdust.edu.cn"),
    ("计算机科学与工程学院", "https://cise.sdust.edu.cn"),
    ("数学与系统科学学院", "https://sxy.sdust.edu.cn"),
    ("经济管理学院", "https://cem.sdust.edu.cn"),
    ("电气与自动化工程学院", "https://xindian.sdust.edu.cn"),
    ("电子信息工程学院", "https://dxxy.sdust.edu.cn"),
    ("化学与生物工程学院", "https://huagong.sdust.edu.cn"),
    ("材料科学与工程学院", "https://cmse.sdust.edu.cn"),
    ("交通学院", "https://jt.sdust.edu.cn"),
    ("文法学院", "https://wenfa.sdust.edu.cn"),
    ("外国语学院", "https://waiyu.sdust.edu.cn"),
    ("艺术学院", "https://art.sdust.edu.cn"),
    ("马克思主义学院", "https://marx.sdust.edu.cn"),
    ("体育学院", "https://tiyu.sdust.edu.cn"),
    ("海洋科学与工程学院", "https://ioe.sdust.edu.cn"),
    ("储能技术学院", "https://est.sdust.edu.cn"),
    ("资源学院", "https://zyxy.sdust.edu.cn"),
    ("智能装备学院", "https://znzb.sdust.edu.cn"),
    ("财经学院", "https://cjxy.sdust.edu.cn"),
    ("斯威本学院", "https://sc.sdust.edu.cn"),
]

# Per-college known list-page paths (discovered by crawling each site).
# Falls back to generic COLLEGE_LIST_CANDIDATES when a college is not listed.
COLLEGE_KNOWN_LISTS: dict[str, list[dict]] = {
    # ── 数学与系统科学学院 ──
    "https://sxy.sdust.edu.cn": [
        {"category": "学院要闻", "path": "/index/xyyw.htm", "max_pages": 5},
        {"category": "动态资讯", "path": "/index/dtzx.htm", "max_pages": 5},
        {"category": "通知公告", "path": "/index/tzgg.htm", "max_pages": 5},
        {"category": "学术动态", "path": "/kxyj/xsdt.htm", "max_pages": 5},
        {"category": "科研动态", "path": "/kxyj/kydt.htm", "max_pages": 5},
    ],
    # ── 经济管理学院 ──
    "https://cem.sdust.edu.cn": [
        {"category": "学院动态", "path": "/index/xydt.htm", "max_pages": 5},
        {"category": "信息公告", "path": "/index/xxgg.htm", "max_pages": 5},
        {"category": "教学动态", "path": "/jyjx/jxdt.htm", "max_pages": 5},
        {"category": "科研动态", "path": "/kxyj/kydt.htm", "max_pages": 5},
    ],
    # ── 电气与自动化工程学院 ──
    "https://xindian.sdust.edu.cn": [
        {"category": "新闻动态", "path": "/xwdt/xyxw.htm", "max_pages": 5},
        {"category": "通知公告", "path": "/xwdt/tzgg.htm", "max_pages": 5},
        {"category": "学术交流", "path": "/jlhz/xsjl.htm", "max_pages": 5},
        {"category": "学工通知", "path": "/xtgz/xxgg/xgtz.htm", "max_pages": 5},
        {"category": "学团新闻", "path": "/xtgz/xxgg/xtxw.htm", "max_pages": 5},
    ],
    # ── 化学与生物工程学院 ──
    "https://huagong.sdust.edu.cn": [
        {"category": "化院风采", "path": "/index/hyfc.htm", "max_pages": 5},
        {"category": "学团动态", "path": "/index/xtdt.htm", "max_pages": 5},
        {"category": "学院动态", "path": "/xyxw/xydt.htm", "max_pages": 5},
        {"category": "党群动态", "path": "/dqgz/dqdt.htm", "max_pages": 5},
    ],
    # ── 材料科学与工程学院 ──
    "https://cmse.sdust.edu.cn": [
        {"category": "学院新闻", "path": "/index/xyxw.htm", "max_pages": 5},
        {"category": "通知公告", "path": "/index/tzgg.htm", "max_pages": 5},
        {"category": "党群动态", "path": "/dqgz/dqdt.htm", "max_pages": 5},
    ],
    # ── 文法学院 ──
    "https://wenfa.sdust.edu.cn": [
        {"category": "新闻动态", "path": "/xwzx/xwdt.htm", "max_pages": 5},
        {"category": "公告通知", "path": "/xwzx/xygg/ggtz.htm", "max_pages": 5},
        {"category": "学术信息", "path": "/kxyj/xsxx.htm", "max_pages": 5},
        {"category": "科研动态", "path": "/kxyj/kydt.htm", "max_pages": 5},
    ],
    # ── 外国语学院 ──
    "https://waiyu.sdust.edu.cn": [
        {"category": "学院新闻", "path": "/index/xyxw.htm", "max_pages": 5},
        {"category": "学团动态", "path": "/xtgz/xtdt.htm", "max_pages": 5},
    ],
    # ── 艺术学院 ──
    "https://art.sdust.edu.cn": [
        {"category": "党建动态", "path": "/dqgz/djdt.htm", "max_pages": 5},
        {"category": "学团动态", "path": "/xtgz1/xtdt.htm", "max_pages": 5},
        {"category": "美育活动", "path": "/ggmy/myhd.htm", "max_pages": 5},
    ],
    # ── 马克思主义学院 ──
    "https://marx.sdust.edu.cn": [
        {"category": "学院新闻", "path": "/xyxw.htm", "max_pages": 5},
        {"category": "工作动态", "path": "/xkjs/gzdt.htm", "max_pages": 5},
    ],
    # ── 体育学院 ──
    "https://tiyu.sdust.edu.cn": [
        {"category": "学院新闻", "path": "/index/xyxw.htm", "max_pages": 5},
        {"category": "通知公告", "path": "/index/tzgg.htm", "max_pages": 5},
    ],
    # ── 储能技术学院 ──
    "https://est.sdust.edu.cn": [
        {"category": "新闻动态", "path": "/syxx/xwdt.htm", "max_pages": 5},
        {"category": "通知公告", "path": "/syxx/tzgg.htm", "max_pages": 5},
        {"category": "学术动态", "path": "/kxyj/xsdt.htm", "max_pages": 5},
    ],
    # ── 资源学院 ──
    "https://zyxy.sdust.edu.cn": [
        {"category": "学院新闻", "path": "/index/xyxw.htm", "max_pages": 5},
        {"category": "通知公告", "path": "/index/tzgg.htm", "max_pages": 5},
        {"category": "学术动态", "path": "/index/xsdt.htm", "max_pages": 5},
    ],
    # ── 智能装备学院 ──
    "https://znzb.sdust.edu.cn": [
        {"category": "学院新闻", "path": "/xyxw.htm", "max_pages": 5},
        {"category": "通知公告", "path": "/tzgg.htm", "max_pages": 5},
        {"category": "教学科研", "path": "/jxky.htm", "max_pages": 5},
        {"category": "学团新闻", "path": "/xtxw.htm", "max_pages": 5},
        {"category": "党建动态", "path": "/djdt.htm", "max_pages": 5},
    ],
    # ── 财经学院 ──
    "https://cjxy.sdust.edu.cn": [
        {"category": "学院新闻", "path": "/xyxw.htm", "max_pages": 5},
        {"category": "通知公告", "path": "/tzgg.htm", "max_pages": 5},
        {"category": "党建动态", "path": "/djzc/djdt.htm", "max_pages": 5},
    ],
    # ── 斯威本学院 ──
    "https://sc.sdust.edu.cn": [
        {"category": "新闻动态", "path": "/xwdt.htm", "max_pages": 5},
        {"category": "通知公告", "path": "/tzgg1.htm", "max_pages": 5},
        {"category": "合作交流", "path": "/hzjl.htm", "max_pages": 5},
        {"category": "学团资讯", "path": "/xtzx.htm", "max_pages": 5},
    ],
    # ── 能源与矿业工程学院 ──
    "https://cms.sdust.edu.cn": [
        {"category": "学院新闻", "path": "/sy/xyxw.htm", "max_pages": 5},
        {"category": "通知公告", "path": "/sy/tzgg.htm", "max_pages": 5},
        {"category": "学术动态", "path": "/sy/xsdt/fwjl.htm", "max_pages": 5},
    ],
    # ── 安全与环境工程学院 ──
    "https://csee.sdust.edu.cn": [
        {"category": "新闻动态", "path": "/syxx/xwdt.htm", "max_pages": 5},
        {"category": "通知公告", "path": "/syxx/tzgg.htm", "max_pages": 5},
        {"category": "党群资讯", "path": "/syxx/dqzx.htm", "max_pages": 5},
        {"category": "教学科研", "path": "/syxx/jxky.htm", "max_pages": 5},
        {"category": "学术交流", "path": "/kxyj/xsjl.htm", "max_pages": 5},
    ],
    # ── 测绘与空间信息学院 ──
    "https://gc.sdust.edu.cn": [
        {"category": "学院新闻", "path": "/xyxw.htm", "max_pages": 5},
        {"category": "通知公告", "path": "/tzgg.htm", "max_pages": 5},
        {"category": "教学科研", "path": "/jxky.htm", "max_pages": 5},
        {"category": "学术讲座", "path": "/xsjz.htm", "max_pages": 5},
    ],
    # ── 地球科学与工程学院 (hybrid: HTM + JSP-based CMS) ──
    "https://cgse.sdust.edu.cn": [
        {"category": "党建动态", "path": "/dqgz/djdt.htm", "max_pages": 5},
        {"category": "学院新闻", "path": "/list_title.jsp?urltype=tree.TreeTempUrl&wbtreeid=1267", "max_pages": 1},
        {"category": "通知公告", "path": "/list_title.jsp?urltype=tree.TreeTempUrl&wbtreeid=1268", "max_pages": 1},
        {"category": "学术动态", "path": "/list_title.jsp?urltype=tree.TreeTempUrl&wbtreeid=1269", "max_pages": 1},
        {"category": "学团动态", "path": "/list_title.jsp?urltype=tree.TreeTempUrl&wbtreeid=1250", "max_pages": 1},
    ],
    # ── 土木工程与建筑学院 ──
    "https://fcea.sdust.edu.cn": [
        {"category": "学院新闻", "path": "/index/xyxw.htm", "max_pages": 5},
        {"category": "通知公告", "path": "/index/tzgg.htm", "max_pages": 5},
        {"category": "科研动态", "path": "/kxyj/kydt.htm", "max_pages": 5},
    ],
    # ── 机械电子工程学院 ──
    "https://cmee.sdust.edu.cn": [
        {"category": "党建动态", "path": "/dqgz/djdt.htm", "max_pages": 5},
        {"category": "通知公告", "path": "/xtzx/tzgg.htm", "max_pages": 5},
        {"category": "学团动态", "path": "/xtzx/xtdt.htm", "max_pages": 5},
    ],
    # ── 海洋科学与工程学院 ──
    "https://ioe.sdust.edu.cn": [
        {"category": "本院新闻", "path": "/index/byxw.htm", "max_pages": 5},
        {"category": "学院通知", "path": "/index/xytz.htm", "max_pages": 5},
        {"category": "学术动态", "path": "/index/xsdt.htm", "max_pages": 5},
    ],
}

# Generic fallback candidates (used when a college is not in COLLEGE_KNOWN_LISTS).
COLLEGE_LIST_CANDIDATES = [
    ("通知公告", ["/tzgg.htm", "/tzgg1.htm", "/xytz.htm", "/index/tzgg.htm"]),
    ("学院新闻", ["/xwdt.htm", "/xyxw.htm", "/xw.htm", "/xydt.htm", "/index/xyxw.htm"]),
    ("学术动态", ["/xsdt.htm", "/xshd.htm", "/kydt.htm", "/index/xsdt.htm"]),
]
COLLEGE_MAX_PAGES = 5

# ─────────────────── HTTP 请求 ───────────────────

_session = requests.Session()
_session.headers.update({"User-Agent": USER_AGENT})
_last_request_time = defaultdict(float)


def _domain(url: str) -> str:
    return urlparse(url).hostname or ""


def fetch(url: str) -> str | None:
    domain = _domain(url)
    elapsed = time.time() - _last_request_time[domain]
    if elapsed < REQUEST_DELAY:
        time.sleep(REQUEST_DELAY - elapsed)

    for attempt in range(MAX_RETRIES + 1):
        try:
            resp = _session.get(url, timeout=REQUEST_TIMEOUT, verify=True)
            _last_request_time[domain] = time.time()
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            if resp.apparent_encoding:
                resp.encoding = resp.apparent_encoding
            return resp.text
        except requests.exceptions.SSLError:
            try:
                resp = _session.get(url, timeout=REQUEST_TIMEOUT, verify=False)
                _last_request_time[domain] = time.time()
                if resp.status_code == 404:
                    return None
                resp.raise_for_status()
                if resp.apparent_encoding:
                    resp.encoding = resp.apparent_encoding
                return resp.text
            except Exception:
                return None
        except Exception as e:
            if attempt < MAX_RETRIES:
                time.sleep(2 * (attempt + 1))
            else:
                log.warning("请求失败 %s: %s", url, e)
                return None
    return None


# ─────────────────── 内容提取与清理 ───────────────────

def extract_body(html: str) -> str | None:
    soup = BeautifulSoup(html, "lxml")

    for tag in soup.find_all(["script", "style", "nav", "header", "footer", "iframe", "noscript"]):
        tag.decompose()
    for comment in soup.find_all(string=lambda t: isinstance(t, Comment)):
        comment.extract()

    content_el = None
    for selector in CONTENT_SELECTORS:
        content_el = soup.select_one(selector)
        if content_el and len(content_el.get_text(strip=True)) > 50:
            break
        content_el = None

    if not content_el:
        return None

    for a in content_el.find_all("a"):
        text = a.get_text(strip=True)
        if text:
            a.replace_with(text)
        else:
            a.decompose()

    for img in content_el.find_all("img"):
        img.decompose()

    parts = []
    for el in content_el.descendants:
        if isinstance(el, str):
            t = el.strip()
            if t:
                parts.append(t)
        elif el.name == "br":
            parts.append("\n")
        elif el.name in ("p", "div", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "table"):
            parts.append("\n")

    raw = "".join(parts)
    return _clean(raw)


def _clean(text: str) -> str | None:
    text = unicodedata.normalize("NFKC", text)
    text = GARBAGE_CHARS_RE.sub("", text)
    text = text.replace("\xa0", " ").replace("　", " ")
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    text = METADATA_RE.sub("", text)
    text = INLINE_META_RE.sub("", text)

    lines = []
    for raw_line in text.split("\n"):
        line = raw_line.strip()
        line = MULTI_SPACES_RE.sub(" ", line)
        if line:
            lines.append(line)

    text = "\n".join(lines)
    text = MULTI_NEWLINES_RE.sub("\n\n", text)
    text = text.strip()

    if len(text) < 60:
        return None
    return text


def extract_title(html: str) -> str | None:
    soup = BeautifulSoup(html, "lxml")
    for sel in ["h1", "div.col_news_title h3", "div.art_title", "span.col_news_title"]:
        el = soup.select_one(sel)
        if el:
            t = el.get_text(strip=True)
            if t and len(t) > 2:
                return re.sub(r"\s+", " ", t)
    tag = soup.find("title")
    if tag:
        t = tag.get_text(strip=True)
        t = re.split(r"[-_—|]", t)[0].strip()
        if t and len(t) > 2:
            return t
    return None


# ─────────────────── 列表页解析 ───────────────────

def _article_urls_from_html(html: str, base_url: str) -> list[str]:
    soup = BeautifulSoup(html, "lxml")
    seen, urls = set(), []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        # Match both absolute "/info/" and relative "info/" article links
        if not re.search(r"(?:^|/)info/\d+/\d+", href) or not href.endswith(".htm"):
            continue
        full = urljoin(base_url, href)
        if full not in seen:
            seen.add(full)
            urls.append(full)
    return urls


def _page_url(base_url: str, list_path: str, page: int) -> str:
    if page == 0:
        return urljoin(base_url, list_path)
    # JSP-based list pages (e.g. cgse) don't follow the /N.htm pagination pattern
    if ".jsp" in list_path:
        return None  # Only first page is supported for JSP lists
    stem = list_path.rsplit(".htm", 1)[0]
    return urljoin(base_url, f"{stem}/{page}.htm")


def crawl_list(base_url: str, list_path: str, max_pages: int) -> list[str]:
    all_urls = []
    for page in range(max_pages):
        url = _page_url(base_url, list_path, page)
        if url is None:
            break
        html = fetch(url)
        if not html:
            break
        urls = _article_urls_from_html(html, base_url)
        if not urls:
            break
        all_urls.extend(urls)
    return list(dict.fromkeys(all_urls))


# ─────────────────── 文件保存 ───────────────────

def _safe_name(name: str, maxlen: int = 80) -> str:
    name = re.sub(r'[\\/:*?"<>|\n\r\t]', "", name)
    name = re.sub(r"\s+", " ", name).strip().strip(".")
    if len(name) > maxlen:
        name = name[:maxlen].rstrip()
    return name or "untitled"


def save(folder: Path, title: str, content: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    base = _safe_name(title)
    path = folder / f"{base}.txt"
    n = 1
    while path.exists():
        path = folder / f"{base}_{n}.txt"
        n += 1
    path.write_text(content, encoding="utf-8")
    return path


# ─────────────────── 进度管理 ───────────────────

class Progress:
    def __init__(self):
        self.done: set[str] = set()
        self.stats: dict = defaultdict(lambda: {"saved": 0, "skip": 0, "fail": 0})
        if PROGRESS_FILE.exists():
            try:
                d = json.loads(PROGRESS_FILE.read_text())
                self.done = set(d.get("done", []))
                log.info("恢复进度: 已处理 %d 个URL", len(self.done))
            except Exception:
                pass

    def flush(self):
        PROGRESS_FILE.write_text(json.dumps(
            {"done": list(self.done), "stats": dict(self.stats)},
            ensure_ascii=False,
        ))

    def record(self, url: str, site: str, status: str):
        self.done.add(url)
        self.stats[site][status] += 1


# ─────────────────── 学院列表页发现 ───────────────────

def discover_college_lists(base_url: str) -> list[dict]:
    # Use pre-discovered paths when available
    if base_url in COLLEGE_KNOWN_LISTS:
        known = COLLEGE_KNOWN_LISTS[base_url]
        log.info("  使用预定义列表页 (%d 个分类)", len(known))
        return known

    # Fallback: probe generic candidate paths
    found = []
    for cat, paths in COLLEGE_LIST_CANDIDATES:
        for p in paths:
            html = fetch(urljoin(base_url, p))
            if html and _article_urls_from_html(html, base_url):
                found.append({"category": cat, "path": p, "max_pages": COLLEGE_MAX_PAGES})
                break
    return found


# ─────────────────── 爬取核心 ───────────────────

def crawl_site(site: dict, prog: Progress) -> int:
    name = site["name"]
    base = site["base_url"]
    saved_count = 0

    log.info("━" * 50)
    log.info("▶ %s  (%s)", name, base)

    for lst in site["lists"]:
        cat = lst["category"]
        log.info("  📂 %s (最多%d页)", cat, lst["max_pages"])

        urls = crawl_list(base, lst["path"], lst["max_pages"])
        new_urls = [u for u in urls if u not in prog.done]
        log.info("    发现 %d 链接, 新 %d", len(urls), len(new_urls))

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
            saved_count += 1

            if saved_count % 25 == 0:
                prog.flush()

    s = prog.stats[name]
    log.info("  ✓ %s 完成: 保存=%d 跳过=%d 失败=%d", name, s["saved"], s["skip"], s["fail"])
    prog.flush()
    return saved_count


# ─────────────────── 入口 ───────────────────

def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    prog = Progress()
    t0 = time.time()

    log.info("=" * 60)
    log.info("Phase 1: 主要站点与职能部门")
    log.info("=" * 60)
    for site in MAIN_SITES:
        try:
            crawl_site(site, prog)
        except Exception as e:
            log.error("站点出错 %s: %s", site["name"], e)
            prog.flush()

    log.info("=" * 60)
    log.info("Phase 2: 各学院网站")
    log.info("=" * 60)
    for cname, curl in COLLEGES:
        try:
            log.info("探测 %s ...", cname)
            lists = discover_college_lists(curl)
            if not lists:
                log.warning("  %s: 未发现列表页, 跳过", cname)
                continue
            log.info("  发现: %s", ", ".join(l["category"] for l in lists))
            crawl_site({"name": cname, "base_url": curl, "lists": lists}, prog)
        except Exception as e:
            log.error("学院出错 %s: %s", cname, e)
            prog.flush()

    elapsed = time.time() - t0
    log.info("=" * 60)
    log.info("全部完成! 用时 %.1f 分钟", elapsed / 60)
    log.info("=" * 60)

    total = {"saved": 0, "skip": 0, "fail": 0}
    for sname in sorted(prog.stats):
        s = prog.stats[sname]
        for k in total:
            total[k] += s[k]
        log.info("  %-24s 保存=%3d 跳过=%3d 失败=%3d", sname, s["saved"], s["skip"], s["fail"])
    log.info("  " + "-" * 52)
    log.info("  %-24s 保存=%3d 跳过=%3d 失败=%3d", "合计", total["saved"], total["skip"], total["fail"])

    summary = {
        "total": total,
        "elapsed_minutes": round(elapsed / 60, 1),
        "sites": dict(prog.stats),
    }
    (OUTPUT_DIR / "crawl_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    prog.flush()


if __name__ == "__main__":
    main()
