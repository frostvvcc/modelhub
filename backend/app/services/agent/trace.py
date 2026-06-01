"""
Agent 调用链追踪系统 (Trace/Span)

记录 Agent 每一步操作的输入、输出、延迟和 token 消耗，
支持可视化回放和性能分析。
"""
import uuid
import time
from typing import List, Optional, Dict, Any
from dataclasses import dataclass, field


@dataclass
class Span:
    """单步操作记录"""
    span_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    name: str = ""
    span_type: str = "generic"
    input_data: Dict[str, Any] = field(default_factory=dict)
    output_data: Dict[str, Any] = field(default_factory=dict)
    start_time: float = 0.0
    end_time: float = 0.0
    latency_ms: int = 0
    tokens_used: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    status: str = "pending"
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def start(self):
        self.start_time = time.time()
        self.status = "running"

    def finish(self, output: Optional[Dict[str, Any]] = None, error: Optional[str] = None):
        self.end_time = time.time()
        self.latency_ms = int((self.end_time - self.start_time) * 1000)
        if output:
            self.output_data = output
        if error:
            self.error = error
            self.status = "error"
        else:
            self.status = "completed"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "span_id": self.span_id,
            "name": self.name,
            "type": self.span_type,
            "input": self.input_data,
            "output": self.output_data,
            "latency_ms": self.latency_ms,
            "tokens_used": self.tokens_used,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "status": self.status,
            "error": self.error,
        }


class TraceContext:
    """完整调用链追踪上下文"""

    def __init__(self, trace_id: Optional[str] = None):
        self.trace_id = trace_id or uuid.uuid4().hex[:16]
        self.spans: List[Span] = []
        self.start_time = time.time()
        self.end_time: float = 0.0
        self.metadata: Dict[str, Any] = {}

    def create_span(self, name: str, span_type: str = "generic", input_data: Optional[Dict[str, Any]] = None) -> Span:
        span = Span(
            name=name,
            span_type=span_type,
            input_data=input_data or {},
        )
        span.start()
        self.spans.append(span)
        return span

    def finish(self):
        self.end_time = time.time()

    @property
    def total_latency_ms(self) -> int:
        if self.end_time:
            return int((self.end_time - self.start_time) * 1000)
        return int((time.time() - self.start_time) * 1000)

    @property
    def total_tokens(self) -> int:
        return sum(s.tokens_used for s in self.spans)

    @property
    def total_prompt_tokens(self) -> int:
        return sum(s.prompt_tokens for s in self.spans)

    @property
    def total_completion_tokens(self) -> int:
        return sum(s.completion_tokens for s in self.spans)

    @property
    def tool_call_count(self) -> int:
        return sum(1 for s in self.spans if s.span_type == "tool_call")

    @property
    def llm_call_count(self) -> int:
        return sum(1 for s in self.spans if s.span_type == "llm_call")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "total_latency_ms": self.total_latency_ms,
            "total_tokens": self.total_tokens,
            "prompt_tokens": self.total_prompt_tokens,
            "completion_tokens": self.total_completion_tokens,
            "llm_calls": self.llm_call_count,
            "tool_calls": self.tool_call_count,
            "spans": [s.to_dict() for s in self.spans],
        }
