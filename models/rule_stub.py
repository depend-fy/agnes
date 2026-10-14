"""离线规则桩 LLM Provider。

设计理由：
- 无 key 或 mode=stub 时使用，保证离线闭环可跑通。
- 输出确定性 RoleJudgement（不依赖网络），model_tag 固定为 "stub"。
- 用于测试与现场无网环境降级。
"""
from __future__ import annotations

import json
from typing import Any, Dict, Optional

from models.base import LLMProvider, LLMResponse


class RuleStubProvider(LLMProvider):
    """确定性桩：根据 prompt 关键词产出结构化判断，不调用网络。"""

    def __init__(self, name: str = "stub", model_tag: str = "stub") -> None:
        self.name = name
        self.model_tag = model_tag
        self.calls_made = 0

    def is_available(self) -> bool:
        # 桩始终"可用"，但不代表真实模型
        return True

    def complete(
        self,
        prompt: str,
        system: str = "",
        json_mode: bool = False,
        timeout_s: float = 60.0,
    ) -> LLMResponse:
        self.calls_made += 1
        parsed = self._deterministic_judge(prompt)
        raw = json.dumps(parsed, ensure_ascii=False)
        return LLMResponse(
            raw_text=raw,
            parsed=parsed,
            model_tag=self.model_tag,
            provider=self.name,
            latency_s=0.0,
            tokens_in=0,
            tokens_out=0,
            cost_estimate=0.0,
            error=None,
        )

    def _deterministic_judge(self, prompt: str) -> Dict[str, Any]:
        """根据 prompt 文本关键词产出确定性结构化判断。

        真实场景下这里会被 LLM 替换；阶段 3 仅用于离线/无 key 降级。
        判断逻辑：
          - prompt 含 "证据" → 证据审查员
          - 含 "复核" / "review" → 独立复核员
          - 否则 → 事实审查员
        所有桩判断都带 model_tag="stub"，明确标记为模拟。
        """
        text = prompt.lower()
        if "证据" in prompt or "evidence" in text:
            return {
                "role": "evidence_reviewer",
                "judgement": "（桩）未接入真实证据源，无法判断证据支持度；建议标记为证据不足。",
                "confidence_note": "离线桩，非真实判断；阶段 4 接入 Crossref/OpenAlex 后替换。",
                "issues": ["missing_evidence"],
            }
        if "复核" in prompt or "review" in text:
            return {
                "role": "independent_reviewer",
                "judgement": "（桩）复核未启用；当前修正为空，无新错误可检查。",
                "confidence_note": "离线桩；阶段 5 启用真实复核后替换。",
                "issues": [],
            }
        return {
            "role": "fact_reviewer",
            "judgement": "（桩）事实审查员初判：需外部检索确认主张真实性；当前无证据，暂无法核验。",
            "confidence_note": "离线桩，非真实判断；阶段 3 接真实模型后替换。",
            "issues": [],
        }
