"""
基于有限状态机的 Agent 编排引擎

状态流转：
  IDLE → PLANNING → TOOL_CALLING → REFLECTING → RESPONDING → DONE
  每个状态有明确的进入/退出条件，支持多 Agent 协作和工具链路追踪。
"""
from enum import Enum
from typing import Optional, Dict, Any
from dataclasses import dataclass, field


class AgentState(str, Enum):
    IDLE = "idle"
    PLANNING = "planning"
    TOOL_CALLING = "tool_calling"
    REFLECTING = "reflecting"
    RESPONDING = "responding"
    DONE = "done"
    ERROR = "error"


TRANSITIONS = {
    AgentState.IDLE: [AgentState.PLANNING],
    AgentState.PLANNING: [AgentState.TOOL_CALLING, AgentState.RESPONDING, AgentState.ERROR],
    AgentState.TOOL_CALLING: [AgentState.REFLECTING, AgentState.ERROR],
    AgentState.REFLECTING: [AgentState.TOOL_CALLING, AgentState.RESPONDING, AgentState.ERROR],
    AgentState.RESPONDING: [AgentState.DONE],
    AgentState.DONE: [],
    AgentState.ERROR: [AgentState.DONE],
}

STATE_LABELS = {
    AgentState.IDLE: "等待中",
    AgentState.PLANNING: "分析问题中...",
    AgentState.TOOL_CALLING: "调用工具中...",
    AgentState.REFLECTING: "分析工具结果中...",
    AgentState.RESPONDING: "生成回答中...",
    AgentState.DONE: "完成",
    AgentState.ERROR: "出错了",
}


@dataclass
class StateTransition:
    from_state: AgentState
    to_state: AgentState
    reason: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


class AgentStateMachine:
    """Agent 有限状态机"""

    def __init__(self):
        self._state = AgentState.IDLE
        self._history: list[StateTransition] = []

    @property
    def state(self) -> AgentState:
        return self._state

    @property
    def label(self) -> str:
        return STATE_LABELS.get(self._state, str(self._state))

    @property
    def history(self) -> list[StateTransition]:
        return list(self._history)

    def can_transition(self, target: AgentState) -> bool:
        return target in TRANSITIONS.get(self._state, [])

    def transition(self, target: AgentState, reason: str = "", metadata: Optional[Dict[str, Any]] = None):
        if not self.can_transition(target):
            raise ValueError(
                f"非法状态转移: {self._state.value} → {target.value}，"
                f"允许: {[s.value for s in TRANSITIONS.get(self._state, [])]}"
            )
        transition = StateTransition(
            from_state=self._state,
            to_state=target,
            reason=reason,
            metadata=metadata or {},
        )
        self._history.append(transition)
        self._state = target

    def to_dict(self) -> Dict[str, Any]:
        return {
            "current_state": self._state.value,
            "label": self.label,
            "transitions": [
                {
                    "from": t.from_state.value,
                    "to": t.to_state.value,
                    "reason": t.reason,
                }
                for t in self._history
            ],
        }
