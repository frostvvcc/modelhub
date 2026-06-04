"""
全局 Token 预算控制器

在 Agent 多轮调用和长对话中，防止 Token 用量失控。
支持按会话级别设置预算上限，超限后强制终止 Agent 循环。
"""
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class BudgetExhaustedError(Exception):
    """Token 预算耗尽"""

    def __init__(self, used: int, limit: int):
        self.used = used
        self.limit = limit
        super().__init__(f"Token 预算耗尽: 已用 {used}/{limit}")


class TokenBudget:
    """
    会话级 Token 预算管理器。

    用法:
        budget = TokenBudget(max_tokens=8000)
        budget.consume(prompt_tokens=500, completion_tokens=200)
        if budget.remaining < 500:
            # 强制进入最终回答
            ...
    """

    def __init__(self, max_tokens: int = 8000):
        self.max_tokens = max_tokens
        self._prompt_tokens = 0
        self._completion_tokens = 0

    def consume(self, prompt_tokens: int = 0, completion_tokens: int = 0):
        self._prompt_tokens += prompt_tokens
        self._completion_tokens += completion_tokens
        if self.used > self.max_tokens:
            raise BudgetExhaustedError(self.used, self.max_tokens)

    @property
    def used(self) -> int:
        return self._prompt_tokens + self._completion_tokens

    @property
    def remaining(self) -> int:
        return max(0, self.max_tokens - self.used)

    @property
    def prompt_tokens(self) -> int:
        return self._prompt_tokens

    @property
    def completion_tokens(self) -> int:
        return self._completion_tokens

    def should_stop(self, reserve: int = 500) -> bool:
        return self.remaining < reserve

    def summary(self) -> dict:
        return {
            "max_tokens": self.max_tokens,
            "used": self.used,
            "remaining": self.remaining,
            "prompt_tokens": self._prompt_tokens,
            "completion_tokens": self._completion_tokens,
        }
