"""独立复核员角色：检查前两个角色的结论，关注误报 / 证据不足 / 修正引入的新错误。

输入：claims + evidence + corrections + prior_judgements + input_text
输出：RoleJudgement 列表
设计理由：
- 独立角色：不共享前两个角色的内部上下文，只看它们的结构化输出 + 原始材料。
- 失败时降级为"复核未通过（原因：调用失败）"，不阻塞管线。
"""
from __future__ import annotations

import json
from typing import Any, Dict, List

from core.enums import RoleType
from core.models import Claim, Correction, Evidence, RoleJudgement
from models.base import LLMProvider
from roles.prompts import SYSTEM_REVIEW, build_user_prompt_review


def _to_dicts(objs) -> List[Dict[str, Any]]:
    return [o.model_dump(mode="json") for o in objs]


def run(
    provider: LLMProvider,
    claims: List[Claim],
    evidence: List[Evidence],
    corrections: List[Correction],
    prior_judgements: List[RoleJudgement],
    input_text: str,
    timeout_s: float = 60.0,
) -> List[RoleJudgement]:
    """调用独立复核员。"""
    user_prompt = build_user_prompt_review(
        _to_dicts(claims),
        _to_dicts(evidence),
        _to_dicts(corrections),
        [_j.model_dump() for _j in prior_judgements],
    )
    resp = provider.complete(user_prompt, system=SYSTEM_REVIEW, json_mode=True, timeout_s=timeout_s)

    if not resp.ok:
        return [
            RoleJudgement(
                role=RoleType.INDEPENDENT_REVIEWER,
                judgement=f"独立复核员调用失败：{resp.error}",
                confidence_note="复核降级",
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
        role=RoleType.INDEPENDENT_REVIEWER,
        judgement=judgement_text[:500],
        confidence_note=conf_text[:500],
        model_tag=resp.model_tag,
    )
    return [judgement] * len(claims)
