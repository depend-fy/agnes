"""事实审查员角色：调用 LLM 对原子主张做初判。

输入：claims + input_text
输出：RoleJudgement 列表（每个 claim 一条）
设计理由：
- 角色层不直接依赖 provider，通过注入的 LLMProvider 调用。
- 失败时不抛异常，返回带 error 的降级 judgement，供 pipeline 决定后续。
"""
from __future__ import annotations

import json
from typing import Any, Dict, List

from core.enums import IssueType, RoleType
from core.models import Claim, RoleJudgement
from models.base import LLMProvider, LLMResponse
from roles.prompts import SYSTEM_FACT, build_user_prompt_factual


def _claims_to_dicts(claims: List[Claim]) -> List[Dict[str, Any]]:
    return [c.model_dump(mode="json") for c in claims]


def run(
    provider: LLMProvider,
    claims: List[Claim],
    input_text: str,
    timeout_s: float = 60.0,
) -> List[RoleJudgement]:
    """调用事实审查员，返回每个 claim 的 judgement。"""
    user_prompt = build_user_prompt_factual(_claims_to_dicts(claims), input_text)
    resp = provider.complete(user_prompt, system=SYSTEM_FACT, json_mode=True, timeout_s=timeout_s)

    if not resp.ok:
        # 降级：所有 claim 标记为未核验，记录错误
        return [
            RoleJudgement(
                role=RoleType.FACT_REVIEWER,
                judgement=f"事实审查员调用失败：{resp.error}",
                confidence_note="降级为未核验",
                model_tag=resp.model_tag,
            )
            for _ in claims
        ]

    # 解析结构化结果（阶段 4 加固：judgement/confidence_note 可能是 dict/list，强制转字符串）
    parsed: Dict[str, Any] = resp.parsed or {}
    judgement_text = parsed.get("judgement", resp.raw_text)
    if not isinstance(judgement_text, str):
        judgement_text = json.dumps(judgement_text, ensure_ascii=False)
    conf_text = parsed.get("confidence_note", "")
    if not isinstance(conf_text, str):
        conf_text = json.dumps(conf_text, ensure_ascii=False)

    judgement = RoleJudgement(
        role=RoleType.FACT_REVIEWER,
        judgement=judgement_text[:500],
        confidence_note=conf_text[:500],
        model_tag=resp.model_tag,
    )
    # 阶段 3 简化：所有 claim 共享一条整体 judgement；
    # 后续可按 issues 拆分到各 claim。
    return [judgement] * len(claims)
