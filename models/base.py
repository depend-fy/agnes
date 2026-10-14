"""LLM 适配层抽象接口。

设计理由：
- 把"调用模型"与"角色逻辑"解耦；角色只依赖 LLMProvider，不关心底层 provider。
- LLMResponse 携带耗时 / token / 成本 / model_tag / 错误，供 pipeline 做成本控制与可追溯。
- model_tag 是区分"真实多模型协同"与"单模型模拟/桩"的关键字段。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class LLMResponse:
    """单次 LLM 调用的完整结果（无论成功与否）。"""

    # 原始文本输出（成功时）
    raw_text: str = ""
    # 解析后的结构化 JSON（如果 prompt 要求 JSON 输出）
    parsed: Optional[Dict[str, Any]] = None
    # 调用元信息
    model_tag: str = "stub"          # "stub" / "agnes" / "deepseek" / 真实模型名
    latency_s: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0
    cost_estimate: float = 0.0       # 美元粗估（阶段 3 先为 0，阶段 7 可填真实单价）
    provider: str = "stub"
    # 错误信息（失败时）
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.error is None


class LLMProvider(ABC):
    """统一 LLM 调用接口。

    实现方需保证：
    - 超时控制（不无限挂起）。
    - 失败时不抛异常到上层，而是返回带 error 的 LLMResponse。
    - 记录调用次数（供成本控制）。
    """

    name: str = "abstract"
    model_tag: str = "abstract"

    calls_made: int = 0

    @abstractmethod
    def complete(
        self,
        prompt: str,
        system: str = "",
        json_mode: bool = False,
        timeout_s: float = 60.0,
    ) -> LLMResponse:
        """调用模型一次，返回 LLMResponse（含错误信息，不抛异常）。"""
        ...

    def is_available(self) -> bool:
        """是否有能力真实调用（有 key 且模式允许）。"""
        return True
