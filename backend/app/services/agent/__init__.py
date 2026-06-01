"""
Agent 引擎模块

自研轻量 Agent 框架，基于 ReAct 模式实现多轮工具调用，
支持有限状态机编排和完整的 Trace/Span 可观测性。
"""
from app.services.agent.tools import BaseTool, KnowledgeSearchTool, DatabaseQueryTool, CalculatorTool, DateTimeTool, TopicAnalysisTool
from app.services.agent.engine import AgentEngine
from app.services.agent.state_machine import AgentState, AgentStateMachine
from app.services.agent.trace import TraceContext, Span

__all__ = [
    "BaseTool", "KnowledgeSearchTool", "DatabaseQueryTool",
    "CalculatorTool", "DateTimeTool", "TopicAnalysisTool",
    "AgentEngine", "AgentState", "AgentStateMachine",
    "TraceContext", "Span",
]
