"""
Agent 工具定义

支持知识库检索、数据库查询、计算器、日期时间等工具。
每个工具定义 OpenAI Function Calling 兼容的 JSON Schema。
"""
import ast
import json
import math
import operator
import re
from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, Dict, List, Optional
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession

from app.utils.logger_config import get_logger

logger = get_logger(__name__)


class ToolSafetyLevel(Enum):
    """工具安全等级 — 决定执行前需要什么级别的检查"""
    SAFE = "safe"
    SENSITIVE = "sensitive"
    DANGEROUS = "dangerous"


class BaseTool(ABC):
    """工具基类"""
    name: str = ""
    description: str = ""
    parameters: Dict[str, Any] = {}
    safety_level: ToolSafetyLevel = ToolSafetyLevel.SAFE

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

    MAX_TOTAL_CONTENT_CHARS = 3000

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

            per_source_budget = self.MAX_TOTAL_CONTENT_CHARS // max(len(sources), 1)

            formatted = []
            for i, s in enumerate(sources):
                content = (s.get("content") or "").strip()
                if len(content) > per_source_budget:
                    content = content[:per_source_budget] + "…"
                formatted.append({
                    "index": i + 1,
                    "content": content,
                    "source": s.get("source", "未知"),
                    "similarity": round(s.get("similarity", 0), 4),
                    "vector_score": round(s.get("vector_score", 0), 4),
                    "bm25_score": round(s.get("bm25_score", 0), 4),
                    "retrieval_method": s.get("retrieval_method", "vector"),
                })
            result = {
                "found": True,
                "count": len(formatted),
                "total_found": rag_result.get("total_found", len(formatted)),
                "sources": formatted,
                "avg_similarity": round(rag_result.get("avg_similarity", 0), 4),
                "vector_db_ids": rag_result.get("vector_db_ids", []),
                "queried_vector_db_ids": rag_result.get("queried_vector_db_ids", []),
                "has_result_db_ids": rag_result.get("has_result_db_ids", []),
                "_raw_rag_result": rag_result,
            }
            graph_context = rag_result.get("graph_context", "")
            if graph_context:
                result["graph_context"] = graph_context
            return result
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

    def __init__(self, session: AsyncSession, user_id: int, school_id: Optional[int] = None):
        self._session = session
        self._user_id = user_id
        self._school_id = school_id

    async def execute(self, query_type: str, organization_id: Optional[int] = None, **kwargs) -> Dict[str, Any]:
        from app.mappers.organization_mapper import AsyncOrganizationMapper
        try:
            if query_type == "organization_tree":
                school_id = self._school_id or await self._resolve_school_id()
                orgs = await AsyncOrganizationMapper.get_by_school(self._session, school_id=school_id)
                tree = []
                for org in orgs:
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
                users = await AsyncUserMapper.get_enterprise_users(self._session)
                return {"type": "user_count", "count": len(users) if users else 0}

            return {"error": f"不支持的查询类型: {query_type}"}
        except Exception as e:
            logger.error(f"数据库查询失败: {e}")
            return {"error": str(e)}

    async def _resolve_school_id(self) -> int:
        """从当前用户所属组织链推断 school_id"""
        try:
            from app.mappers.user_mapper import AsyncUserMapper
            user = await AsyncUserMapper.get_user_by_id(self._session, self._user_id)
            if user and hasattr(user, 'school_id') and user.school_id:
                return user.school_id
        except Exception:
            pass
        return 1


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

    _SAFE_OPERATORS = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.FloorDiv: operator.floordiv,
        ast.Mod: operator.mod,
        ast.Pow: operator.pow,
        ast.USub: operator.neg,
        ast.UAdd: operator.pos,
    }

    _SAFE_FUNCTIONS = {
        "abs": abs, "round": round, "min": min, "max": max,
        "sqrt": math.sqrt, "pow": math.pow, "log": math.log, "log2": math.log2, "log10": math.log10,
        "sin": math.sin, "cos": math.cos, "tan": math.tan,
        "asin": math.asin, "acos": math.acos, "atan": math.atan,
        "ceil": math.ceil, "floor": math.floor,
    }

    _SAFE_CONSTANTS = {"pi": math.pi, "e": math.e}

    def _safe_eval(self, node: ast.AST) -> Any:
        """递归求值 AST 节点，仅允许数字、运算符和白名单函数"""
        if isinstance(node, ast.Expression):
            return self._safe_eval(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.Name) and node.id in self._SAFE_CONSTANTS:
            return self._SAFE_CONSTANTS[node.id]
        if isinstance(node, ast.BinOp) and type(node.op) in self._SAFE_OPERATORS:
            left = self._safe_eval(node.left)
            right = self._safe_eval(node.right)
            return self._SAFE_OPERATORS[type(node.op)](left, right)
        if isinstance(node, ast.UnaryOp) and type(node.op) in self._SAFE_OPERATORS:
            return self._SAFE_OPERATORS[type(node.op)](self._safe_eval(node.operand))
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in self._SAFE_FUNCTIONS:
                args = [self._safe_eval(a) for a in node.args]
                return self._SAFE_FUNCTIONS[node.func.id](*args)
            raise ValueError(f"不允许的函数: {ast.dump(node.func)}")
        raise ValueError(f"不支持的表达式节点: {type(node).__name__}")

    async def execute(self, expression: str, **kwargs) -> Dict[str, Any]:
        try:
            cleaned = expression.replace('^', '**')
            tree = ast.parse(cleaned, mode='eval')
            result = self._safe_eval(tree)
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


def get_default_tools(
    session: AsyncSession,
    model_config_id: int,
    user_id: int,
    vector_db_ids: Optional[List[int]] = None,
) -> List[BaseTool]:
    tools: List[BaseTool] = []
    if vector_db_ids:
        tools.append(KnowledgeSearchTool(session, model_config_id, user_id, vector_db_ids))
    tools.extend([
        DatabaseQueryTool(session, user_id),
        CalculatorTool(),
        DateTimeTool(),
    ])
    return tools


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
