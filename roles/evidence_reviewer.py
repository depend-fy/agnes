"""证据审查员角色：根据检索到的证据判断每条主张的支持程度。

输入：claims + evidence + input_text
输出：RoleJudgement 列表
设计理由：
- 证据为空时，judge 必须明确标注"证据不足"，不得臆测支持。
- 区分直接支持 / 部分支持 / 反驳 / 无关（阶段 4 检索接入后才有实质证据）。
"""
from __future__ import annotations

import json
from typing import Any, Dict, List

from core.enums import RoleType
from core.models import Claim, Evidence, RoleJudgement
from models.base import LLMProvider
from roles.prompts import SYSTEM_EVIDENCE, build_user_prompt_evidence


def _claims_to_dicts(claims: List[Claim]) -> List[Dict[str, Any]]:
    return [c.model_dump(mode="json") for c in claims]


def _evidence_to_dicts(evidence: List[Evidence]) -> List[Dict[str, Any]]:
    return [e.model_dump(mode="json") for e in evidence]


def run(
    provider: LLMProvider,
    claims: List[Claim],
    evidence: List[Evidence],
    input_text: str,
    timeout_s: float = 60.0,
) -> List[RoleJudgement]:
    """调用证据审查员。"""
    user_prompt = build_user_prompt_evidence(
        _claims_to_dicts(claims), _evidence_to_dicts(evidence), input_text
    )
    resp = provider.complete(user_prompt, system=SYSTEM_EVIDENCE, json_mode=True, timeout_s=timeout_s)

    if not resp.ok:
        return [
            RoleJudgement(
                role=RoleType.EVIDENCE_REVIEWER,
                judgement=f"证据审查员调用失败：{resp.error}",
                confidence_note="降级为证据不足",
                model_tag=resp.model_tag,
            )
            for _ in claims
        ]

    # 解析结构化结果（阶段 4 加固：judgement/confidence_note 可能是 dict/list，强制转字符串）
    parsed: Dict[str, Any] = resp.parsed or {}
    judgement_text = parsed.get("judgement", resp.raw_text)
    if not isinstance(judgement_text, str):
        import json as _json
        judgement_text = _json.dumps(judgement_text, ensure_ascii=False)
    conf_text = parsed.get("confidence_note", "")
    if not isinstance(conf_text, str):
        import json as _json
        conf_text = _json.dumps(conf_text, ensure_ascii=False)

    judgement = RoleJudgement(
        role=RoleType.EVIDENCE_REVIEWER,
        judgement=judgement_text[:500],
        confidence_note=conf_text[:500],
        model_tag=resp.model_tag,
    )
    return [judgement] * len(claims)
