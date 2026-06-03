"""
Agent 工具定义

支持知识库检索、数据库查询、计算器、日期时间、话题分析等 5 种工具。
每个工具定义 OpenAI Function Calling 兼容的 JSON Schema。
"""
import json
import re
import math
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession

from app.utils.logger_config import get_logger

logger = get_logger(__name__)


class BaseTool(ABC):
    """工具基类"""
    name: str = ""
    description: str = ""
    parameters: Dict[str, Any] = {}

    def to_openai_tool(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            }
        }

    @abstractmethod
    async def execute(self, **kwargs) -> Dict[str, Any]:
        raise NotImplementedError


class KnowledgeSearchTool(BaseTool):
    """知识库检索工具 — 包装现有 RAG 管线"""
    name = "knowledge_search"
    description = "从知识库中检索与用户问题相关的信息。当需要查找学校政策、课程信息、文件资料等知识库中可能存在的内容时使用此工具。"
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "要检索的查询文本，应该是一个清晰的搜索关键词或问题"
            },
        },
        "required": ["query"]
    }

    def __init__(self, session: AsyncSession, model_config_id: int, user_id: int,
                 vector_db_ids: Optional[List[int]] = None):
        self._session = session
        self._model_config_id = model_config_id
        self._user_id = user_id
        self._vector_db_ids = vector_db_ids

    async def execute(self, query: str, **kwargs) -> Dict[str, Any]:
        from app.services.vector_service import AsyncVectorService
        try:
            rag_result = await AsyncVectorService.query_vector_by_model(
                self._session,
                self._model_config_id,
                query,
                user_id=self._user_id,
                extra_vector_db_ids=self._vector_db_ids,
            )
            sources = rag_result.get("sources", [])
            if not sources:
                return {"found": False, "message": "知识库中未找到相关信息", "sources": []}

            formatted = []
            for i, s in enumerate(sources[:3]):
                formatted.append({
                    "index": i + 1,
                    "content": (s.get("content") or "")[:300],
                    "source": s.get("source", "未知"),
                    "similarity": round(s.get("similarity", 0), 4),
                })
            return {
                "found": True,
                "count": len(formatted),
                "sources": formatted,
                "avg_similarity": round(rag_result.get("avg_similarity", 0), 4),
                "_raw_rag_result": rag_result,
            }
        except Exception as e:
            logger.error(f"知识库检索失败: {e}")
            return {"found": False, "error": str(e), "sources": []}


class DatabaseQueryTool(BaseTool):
    """数据库查询工具 — 查询组织、用户等结构化数据"""
    name = "database_query"
    description = "查询学校组织架构信息，包括学院、专业、班级等。当用户询问学校组织结构、院系设置等信息时使用。"
    parameters = {
        "type": "object",
        "properties": {
            "query_type": {
                "type": "string",
                "enum": ["organization_tree", "organization_info", "user_count"],
                "description": "查询类型：organization_tree=组织架构树, organization_info=组织详情, user_count=用户统计"
            },
            "organization_id": {
                "type": "integer",
                "description": "组织 ID（可选，不传则查询顶层）"
            },
        },
        "required": ["query_type"]
    }

    def __init__(self, session: AsyncSession, user_id: int):
        self._session = session
        self._user_id = user_id

    async def execute(self, query_type: str, organization_id: Optional[int] = None, **kwargs) -> Dict[str, Any]:
        from app.mappers.organization_mapper import AsyncOrganizationMapper
        try:
            if query_type == "organization_tree":
                orgs = await AsyncOrganizationMapper.get_all_organizations(self._session)
                tree = []
                for org in orgs[:20]:
                    tree.append({
                        "id": org.id,
                        "name": org.name,
                        "type": org.type,
                        "parent_id": org.parent_id,
                    })
                return {"type": "organization_tree", "data": tree, "count": len(tree)}

            elif query_type == "organization_info" and organization_id:
                org = await AsyncOrganizationMapper.get_organization_by_id(self._session, organization_id)
                if org:
                    return {
                        "type": "organization_info",
                        "data": {"id": org.id, "name": org.name, "type": org.type, "code": org.code},
                    }
                return {"type": "organization_info", "error": "组织不存在"}

            elif query_type == "user_count":
                from app.mappers.user_mapper import AsyncUserMapper
                users = await AsyncUserMapper.get_all_users(self._session)
                return {"type": "user_count", "count": len(users) if users else 0}

            return {"error": f"不支持的查询类型: {query_type}"}
        except Exception as e:
            logger.error(f"数据库查询失败: {e}")
            return {"error": str(e)}


class CalculatorTool(BaseTool):
    """安全计算器工具"""
    name = "calculator"
    description = "执行数学计算。支持加减乘除、幂运算、三角函数、对数等。当需要进行数值计算时使用。"
    parameters = {
        "type": "object",
        "properties": {
            "expression": {
                "type": "string",
                "description": "要计算的数学表达式，如 '2 + 3 * 4'、'sqrt(16)'、'sin(pi/2)'"
            }
        },
        "required": ["expression"]
    }

    SAFE_FUNCTIONS = {
        "abs": abs, "round": round, "min": min, "max": max,
        "sqrt": math.sqrt, "pow": math.pow, "log": math.log, "log2": math.log2, "log10": math.log10,
        "sin": math.sin, "cos": math.cos, "tan": math.tan,
        "asin": math.asin, "acos": math.acos, "atan": math.atan,
        "ceil": math.ceil, "floor": math.floor,
        "pi": math.pi, "e": math.e,
    }

    async def execute(self, expression: str, **kwargs) -> Dict[str, Any]:
        try:
            cleaned = re.sub(r'[^0-9+\-*/().,%^ a-zA-Z_]', '', expression)
            if not cleaned.strip():
                return {"error": "无效表达式"}
            cleaned = cleaned.replace('^', '**')
            result = eval(cleaned, {"__builtins__": {}}, self.SAFE_FUNCTIONS)
            return {"expression": expression, "result": result}
        except Exception as e:
            return {"expression": expression, "error": f"计算失败: {str(e)}"}


class DateTimeTool(BaseTool):
    """日期时间工具"""
    name = "datetime_info"
    description = "获取当前日期时间信息，或进行日期计算。当需要知道当前时间、日期差计算等场景时使用。"
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["now", "diff", "format"],
                "description": "操作类型：now=当前时间, diff=日期差, format=格式化"
            },
            "date1": {
                "type": "string",
                "description": "日期1（格式 YYYY-MM-DD）"
            },
            "date2": {
                "type": "string",
                "description": "日期2（格式 YYYY-MM-DD）"
            },
        },
        "required": ["action"]
    }

    async def execute(self, action: str, date1: Optional[str] = None, date2: Optional[str] = None, **kwargs) -> Dict[str, Any]:
        try:
            now = datetime.now()
            if action == "now":
                return {
                    "datetime": now.strftime("%Y-%m-%d %H:%M:%S"),
                    "date": now.strftime("%Y-%m-%d"),
                    "time": now.strftime("%H:%M:%S"),
                    "weekday": ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][now.weekday()],
                    "timestamp": int(now.timestamp()),
                }
            elif action == "diff" and date1 and date2:
                d1 = datetime.strptime(date1, "%Y-%m-%d")
                d2 = datetime.strptime(date2, "%Y-%m-%d")
                delta = (d2 - d1).days
                return {"date1": date1, "date2": date2, "diff_days": delta}
            elif action == "diff" and date1:
                d1 = datetime.strptime(date1, "%Y-%m-%d")
                delta = (now - d1).days
                return {"date1": date1, "date2": now.strftime("%Y-%m-%d"), "diff_days": delta}
            return {"error": f"参数不足: action={action}"}
        except Exception as e:
            return {"error": str(e)}


class TopicAnalysisTool(BaseTool):
    """话题分析工具 — 分析用户意图和消息主题"""
    name = "topic_analysis"
    description = "分析用户消息的主题和意图，判断问题类别。当需要对复杂问题进行分类或理解用户真正意图时使用。"
    parameters = {
        "type": "object",
        "properties": {
            "message": {
                "type": "string",
                "description": "要分析的用户消息"
            },
            "context": {
                "type": "string",
                "description": "对话上下文摘要（可选）"
            },
        },
        "required": ["message"]
    }

    async def execute(self, message: str, context: Optional[str] = None, **kwargs) -> Dict[str, Any]:
        keywords = {
            "学校": "school_info", "学院": "school_info", "专业": "school_info", "班级": "school_info",
            "课程": "course_info", "考试": "exam_info", "成绩": "grade_info",
            "图书": "library_info", "宿舍": "dorm_info", "食堂": "canteen_info",
            "政策": "policy_info", "规定": "policy_info", "制度": "policy_info",
            "计算": "calculation", "多少": "calculation",
            "时间": "datetime", "日期": "datetime", "几号": "datetime",
        }
        detected_topics = []
        for keyword, topic in keywords.items():
            if keyword in message and topic not in detected_topics:
                detected_topics.append(topic)

        return {
            "message_length": len(message),
            "detected_topics": detected_topics if detected_topics else ["general"],
            "has_question": "?" in message or "？" in message or any(w in message for w in ["什么", "怎么", "为什么", "哪", "吗", "几"]),
            "suggested_tools": self._suggest_tools(detected_topics),
        }

    @staticmethod
    def _suggest_tools(topics: List[str]) -> List[str]:
        tool_map = {
            "school_info": ["knowledge_search", "database_query"],
            "course_info": ["knowledge_search"],
            "policy_info": ["knowledge_search"],
            "calculation": ["calculator"],
            "datetime": ["datetime_info"],
        }
        tools = set()
        for topic in topics:
            tools.update(tool_map.get(topic, ["knowledge_search"]))
        return list(tools) if tools else ["knowledge_search"]


def get_default_tools(
    session: AsyncSession,
    model_config_id: int,
    user_id: int,
    vector_db_ids: Optional[List[int]] = None,
) -> List[BaseTool]:
    return [
        KnowledgeSearchTool(session, model_config_id, user_id, vector_db_ids),
        DatabaseQueryTool(session, user_id),
        CalculatorTool(),
        DateTimeTool(),
        TopicAnalysisTool(),
    ]


def get_tools_for_query(
    message: str,
    session: AsyncSession,
    model_config_id: int,
    user_id: int,
    vector_db_ids: Optional[List[int]] = None,
) -> List[BaseTool]:
    """
    动态工具注册：根据用户消息语义按需加载工具，
    减少每次 LLM 调用携带的工具定义 token 开销。
    """
    tools: List[BaseTool] = [
        KnowledgeSearchTool(session, model_config_id, user_id, vector_db_ids),
    ]
    if any(kw in message for kw in ("学院", "专业", "班级", "组织", "院系", "学校")):
        tools.append(DatabaseQueryTool(session, user_id))
    if any(kw in message for kw in ("计算", "算", "等于", "求解", "加", "减", "乘", "除", "%")):
        tools.append(CalculatorTool())
    if any(kw in message for kw in ("几点", "几号", "日期", "时间", "星期", "今天", "明天", "昨天")):
        tools.append(DateTimeTool())
    return tools
