"""
Query 改写模块

解决用户口语化提问和知识库书面用词不匹配的问题。

三种能力：
1. Multi-Query Rewriting：一个问题改写成多个检索 query，多路召回后合并
2. HyDE（Hypothetical Document Embedding）：让 LLM 生成假设答案，用答案文本去检索
3. 结构化约束提取：从用户查询中提取时间、院系等硬约束，用于 metadata 过滤
"""
import asyncio
import json
import re
from typing import List, Dict, Optional, Any
from dataclasses import dataclass, field
from openai import AsyncOpenAI
from app.config import settings
from app.utils.logger_config import get_logger

logger = get_logger(__name__)


# ------------------------------------------------------------------
# 结构化约束提取
# ------------------------------------------------------------------

@dataclass
class QueryConstraints:
    """从用户查询中提取的结构化约束"""
    year: Optional[str] = None
    department: Optional[str] = None
    category: Optional[str] = None
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    semantic_query: str = ""
    raw_query: str = ""

    def has_constraints(self) -> bool:
        return bool(self.year or self.department or self.category or self.date_from or self.date_to)

    def to_chromadb_where(self) -> Optional[Dict]:
        """转换为 ChromaDB where 过滤条件"""
        conditions = []
        if self.year:
            conditions.append({"publish_year": self.year})
        if self.department:
            conditions.append({"department": self.department})
        if self.category:
            conditions.append({"category": self.category})
        if not conditions:
            return None
        if len(conditions) == 1:
            return conditions[0]
        return {"$and": conditions}

    def to_es_filter(self) -> List[Dict]:
        """转换为 Elasticsearch filter 条件"""
        filters = []
        if self.year:
            filters.append({"term": {"publish_year": self.year}})
        if self.department:
            filters.append({"term": {"department": self.department}})
        if self.category:
            filters.append({"term": {"category": self.category}})
        if self.date_from or self.date_to:
            date_range = {}
            if self.date_from:
                date_range["gte"] = self.date_from
            if self.date_to:
                date_range["lte"] = self.date_to
            filters.append({"range": {"publish_date": date_range}})
        return filters

    def to_prompt_hint(self) -> str:
        """生成给 LLM 的约束提示，用于生成阶段校验"""
        parts = []
        if self.year:
            parts.append(f"年份={self.year}年")
        if self.department:
            parts.append(f"院系/部门={self.department}")
        if self.category:
            parts.append(f"分类={self.category}")
        if self.date_from:
            parts.append(f"起始日期={self.date_from}")
        if self.date_to:
            parts.append(f"截止日期={self.date_to}")
        return "、".join(parts)


# 院系名称的各种简称 → 全称映射（用于规则匹配）
_DEPARTMENT_ALIASES = {
    "计算机": "计算机科学与工程学院",
    "计算机学院": "计算机科学与工程学院",
    "计科": "计算机科学与工程学院",
    "材料": "材料科学与工程学院",
    "材料学院": "材料科学与工程学院",
    "机电": "机械电子工程学院",
    "机电学院": "机械电子工程学院",
    "电气": "电气与自动化工程学院",
    "电气学院": "电气与自动化工程学院",
    "电子": "电子信息工程学院",
    "电信": "电子信息工程学院",
    "电信学院": "电子信息工程学院",
    "测绘": "测绘与空间信息学院",
    "测绘学院": "测绘与空间信息学院",
    "地科": "地球科学与工程学院",
    "地科学院": "地球科学与工程学院",
    "安环": "安全与环境工程学院",
    "安环学院": "安全与环境工程学院",
    "化生": "化学与生物工程学院",
    "化生学院": "化学与生物工程学院",
    "交通": "交通学院",
    "交通学院": "交通学院",
    "海洋": "海洋科学与工程学院",
    "海洋学院": "海洋科学与工程学院",
    "经管": "经济管理学院",
    "经管学院": "经济管理学院",
    "财经": "财经学院",
    "财经学院": "财经学院",
    "数学": "数学与系统科学学院",
    "数学学院": "数学与系统科学学院",
    "文法": "文法学院",
    "文法学院": "文法学院",
    "外语": "外国语学院",
    "外语学院": "外国语学院",
    "艺术": "艺术学院",
    "艺术学院": "艺术学院",
    "马院": "马克思主义学院",
    "马克思": "马克思主义学院",
    "储能": "储能技术学院",
    "储能学院": "储能技术学院",
    "智能装备": "智能装备学院",
    "智装": "智能装备学院",
    "创新创业": "创新创业学院",
    "土木": "土木工程与建筑学院",
    "土建": "土木工程与建筑学院",
    "教务处": "教务处",
    "教务": "教务处",
    "研究生院": "研究生院",
    "学生处": "学生工作处",
    "学工处": "学生工作处",
    "图书馆": "图书馆",
}

_YEAR_RE = re.compile(r'(\d{4})\s*年')
_DATE_RANGE_RE = re.compile(r'(\d{4})[年/-](\d{1,2})[月/-](?:(\d{1,2})[日号]?)?')


def extract_constraints_rule(query: str) -> QueryConstraints:
    """规则提取：从查询中用正则和关键词匹配提取约束（零 LLM 调用）"""
    constraints = QueryConstraints(raw_query=query, semantic_query=query)

    # 提取年份
    year_match = _YEAR_RE.search(query)
    if year_match:
        year = year_match.group(1)
        if 1990 <= int(year) <= 2030:
            constraints.year = year

    # 提取院系
    for alias, full_name in sorted(_DEPARTMENT_ALIASES.items(), key=lambda x: -len(x[0])):
        if alias in query:
            constraints.department = full_name
            break

    return constraints


async def extract_constraints_llm(
    query: str,
    model: str = None,
) -> QueryConstraints:
    """
    LLM 约束提取：用 LLM 从自然语言查询中提取结构化约束。
    先用规则快速匹配，匹配不到再调 LLM。
    """
    # 先尝试规则提取
    rule_result = extract_constraints_rule(query)
    if rule_result.has_constraints():
        logger.info(f"约束提取(规则): year={rule_result.year}, dept={rule_result.department}")
        return rule_result

    # 规则提取不到，调 LLM
    model = model or settings.rag_llm_model
    client = _get_rewrite_client()

    prompt = (
        "你是一个查询解析器。从用户的问题中提取结构化约束条件。\n\n"
        "需要提取的字段：\n"
        "- year: 年份（如 2019、2020），如果未提及则为 null\n"
        "- department: 院系或部门名称（如 计算机科学与工程学院、教务处），如果未提及则为 null\n"
        "- category: 信息分类（如 通知公告、学院新闻、招聘信息），如果未提及则为 null\n"
        "- semantic_query: 去掉时间和院系约束后的语义查询部分\n\n"
        "只输出 JSON，格式：\n"
        '{"year": "2019", "department": "计算机科学与工程学院", "category": null, "semantic_query": "活动"}\n\n'
        f"用户问题：{query}"
    )

    try:
        resp = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=200,
            temperature=0.0,
        )
        text = resp.choices[0].message.content.strip()

        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            parsed = json.loads(text[start:end])
        else:
            logger.warning(f"约束提取输出格式异常: {text[:100]}")
            return QueryConstraints(raw_query=query, semantic_query=query)

        constraints = QueryConstraints(
            year=parsed.get("year"),
            department=parsed.get("department"),
            category=parsed.get("category"),
            semantic_query=parsed.get("semantic_query") or query,
            raw_query=query,
        )

        # 对 LLM 输出的院系名做模糊匹配修正
        if constraints.department:
            dept = constraints.department
            if dept in _DEPARTMENT_ALIASES:
                constraints.department = _DEPARTMENT_ALIASES[dept]
            elif dept not in _DEPARTMENT_ALIASES.values():
                for alias, full in _DEPARTMENT_ALIASES.items():
                    if alias in dept or dept in full:
                        constraints.department = full
                        break

        logger.info(
            f"约束提取(LLM): year={constraints.year}, "
            f"dept={constraints.department}, cat={constraints.category}"
        )
        return constraints

    except Exception as e:
        logger.error(f"LLM 约束提取失败: {e}")
        return extract_constraints_rule(query)

_rewrite_client: AsyncOpenAI = None


def _get_rewrite_client() -> AsyncOpenAI:
    global _rewrite_client
    if _rewrite_client is None:
        _rewrite_client = AsyncOpenAI(
            api_key=settings.rag_llm_api_key or settings.embedding_api_key,
            base_url=settings.rag_llm_base_url or settings.embedding_base_url,
        )
    return _rewrite_client


async def rewrite_query(
    query: str,
    n_rewrites: int = 3,
    model: str = None,
) -> List[str]:
    """
    Multi-Query Rewriting：将用户的口语化问题改写为多个检索友好的 query。

    原理：用户说"毕设查重怎么弄"，知识库里写的是"毕业设计论文查重检测通知"。
    LLM 改写成多个角度的 query，每个 query 用不同的措辞检索，
    多路召回合并后覆盖面更广。

    Args:
        query: 用户原始问题
        n_rewrites: 生成的改写 query 数量
        model: 用于改写的 LLM 模型

    Returns:
        改写后的 query 列表（包含原始 query）
    """
    model = model or settings.rag_llm_model
    client = _get_rewrite_client()

    prompt = (
        f"你是一个搜索查询优化器。用户提了一个问题，请将它改写成 {n_rewrites} 个不同角度的检索查询，"
        f"用于在{settings.rag_domain_description}中搜索相关文档。\n\n"
        f"要求：\n"
        f"1. 每个改写使用不同的关键词和表述方式\n"
        f"2. 覆盖问题可能涉及的不同方面\n"
        f"3. 使用正式、书面的措辞（知识库文档是官方通知）\n"
        f"4. 只输出 JSON 数组，格式：[\"query1\", \"query2\", \"query3\"]\n\n"
        f"用户问题：{query}"
    )

    try:
        resp = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=300,
            temperature=0.7,
        )
        text = resp.choices[0].message.content.strip()

        start = text.find("[")
        end = text.rfind("]") + 1
        if start >= 0 and end > start:
            rewrites = json.loads(text[start:end])
            rewrites = [q.strip() for q in rewrites if isinstance(q, str) and q.strip()]
        else:
            logger.warning(f"Query 改写输出格式异常: {text[:100]}")
            return [query]

        # 原始 query 始终保留在第一位
        all_queries = [query] + [q for q in rewrites if q != query]
        logger.info(f"Query 改写: '{query[:30]}...' → {len(all_queries)} 个 query")
        return all_queries

    except Exception as e:
        logger.error(f"Query 改写失败，使用原始 query: {e}")
        return [query]


async def condense_follow_up(
    current_question: str,
    chat_history: List[Dict[str, str]],
    model: str = None,
) -> str:
    """
    Multi-turn Query Reformulation：结合对话历史，将追问补全为独立的检索查询。

    解决问题：用户追问"截止日期呢？"时，RAG 检索不知道在问什么的截止日期。
    本函数将追问 + 上下文合并成一个脱离对话也能理解的独立查询。

    示例：
        历史: "毕设查重流程是什么？" → "查重需要登录系统提交..."
        追问: "截止日期呢？"
        输出: "毕业设计论文查重的截止日期是什么时候？"

    Args:
        current_question: 用户当前追问
        chat_history: 之前的对话消息列表（正序），每条 {"role": "user"|"assistant", "content": "..."}
        model: 用于改写的 LLM 模型

    Returns:
        补全后的独立查询（如果改写失败则返回原始问题）
    """
    model = model or settings.rag_llm_model
    if not chat_history:
        return current_question

    client = _get_rewrite_client()

    history_text = ""
    for msg in chat_history[-6:]:
        role = "用户" if msg.get("role") == "user" else "助手"
        content = (msg.get("content") or "")[:300]
        history_text += f"{role}: {content}\n"

    prompt = (
        "你是一个查询改写器。根据对话历史，将用户的最新追问改写成一个独立的、完整的检索查询。\n\n"
        "规则：\n"
        "1. 改写后的查询必须脱离对话上下文也能被理解\n"
        "2. 保留用户追问的核心意图\n"
        "3. 使用正式、书面的措辞\n"
        "4. 如果追问本身已经是一个完整的独立问题，直接原样输出即可\n"
        "5. 只输出改写后的查询文本，不要任何解释\n\n"
        f"对话历史：\n{history_text}\n"
        f"用户追问：{current_question}\n\n"
        "改写后的独立查询："
    )

    try:
        resp = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=150,
            temperature=0.0,
        )
        condensed = resp.choices[0].message.content.strip()
        condensed = condensed.strip('"').strip('“').strip('”')
        if condensed:
            logger.info(f"Query 补全: '{current_question[:30]}' → '{condensed[:50]}'")
            return condensed
        return current_question

    except Exception as e:
        logger.error(f"Query 补全失败，使用原始问题: {e}")
        return current_question


async def hyde_rewrite(
    query: str,
    model: str = None,
) -> str:
    """
    HyDE (Hypothetical Document Embedding)：
    让 LLM 生成一段"假设的理想答案"，然后用这段文本的 embedding 去检索。

    原理：用户的问题 embedding 和文档 embedding 可能在向量空间中距离较远，
    但 LLM 生成的"假设答案"在措辞上会更接近知识库文档的风格，
    从而在向量空间中更容易匹配到正确的文档。

    Args:
        query: 用户原始问题
        model: 用于生成假设答案的 LLM 模型

    Returns:
        假设的答案文本（用于替代原始 query 做向量检索）
    """
    model = model or settings.rag_llm_model
    client = _get_rewrite_client()

    prompt = (
        "请针对以下问题，写一段简短的回答（100-200字），"
        f"假设你是该领域的工作人员，用正式的通知文体回答。\n"
        f"领域：{settings.rag_domain_description}\n"
        "不需要完全准确，只需要风格和用词接近官方文档即可。\n\n"
        f"问题：{query}\n\n回答："
    )

    try:
        resp = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=250,
            temperature=0.5,
        )
        hyde_text = resp.choices[0].message.content.strip()
        logger.info(f"HyDE 生成: '{query[:30]}...' → {len(hyde_text)} 字符的假设文档")
        return hyde_text

    except Exception as e:
        logger.error(f"HyDE 生成失败，使用原始 query: {e}")
        return query
