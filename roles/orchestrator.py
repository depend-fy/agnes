"""角色编排：按顺序调用三个角色，汇总 judgement。

设计理由：
- 顺序：事实审查员 → 证据审查员 → 独立复核员。
- 每个角色拿到前序角色的结构化输出（不共享内部上下文），保证独立性。
- 调用次数控制：每次检测 3 个角色 = 3 次 LLM 调用（阶段 3 单模型模拟多角色）；
  若接真实多模型也是 3 次（每角色 1 次），预算内。
- 所有 LLMResponse 的元信息（耗时/token/成本/model_tag）汇总到 metadata，供报告追溯。
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from core.enums import RoleType
from core.models import Claim, Correction, Evidence, RoleJudgement
from models.base import LLMProvider
from roles import fact_reviewer, evidence_reviewer, independent_reviewer


def run_all_roles(
    providers: Dict[RoleType, LLMProvider],
    claims: List[Claim],
    evidence: List[Evidence],
    input_text: str,
    corrections: Optional[List[Correction]] = None,
    timeout_s: float = 60.0,
) -> Dict[str, Any]:
    """顺序调用三角色，返回 {judgements, metadata}。

    metadata 含：
      - per_role: {角色: [每条 judgement]}
      - llm_calls: [{role, model_tag, latency_s, tokens_in/out, ok, error}]
      - model_tags: {角色: model_tag}（区分真实/桩）
    """
    corrections = corrections or []
    all_judgements: List[RoleJudgement] = []
    llm_calls: List[Dict[str, Any]] = []
    model_tags: Dict[str, str] = {}
    started = time.time()

    # 1. 事实审查员
    fact_judgements = fact_reviewer.run(
        providers[RoleType.FACT_REVIEWER], claims, input_text, timeout_s
    )
    all_judgements.extend(fact_judgements)
    model_tags["fact_reviewer"] = fact_judgements[0].model_tag if fact_judgements else "unknown"

    # 2. 证据审查员
    ev_judgements = evidence_reviewer.run(
        providers[RoleType.EVIDENCE_REVIEWER], claims, evidence, input_text, timeout_s
    )
    all_judgements.extend(ev_judgements)
    model_tags["evidence_reviewer"] = ev_judgements[0].model_tag if ev_judgements else "unknown"

    # 3. 独立复核员
    review_judgements = independent_reviewer.run(
        providers[RoleType.INDEPENDENT_REVIEWER],
        claims,
        evidence,
        corrections,
        all_judgements,
        input_text,
        timeout_s,
    )
    all_judgements.extend(review_judgements)
    model_tags["independent_reviewer"] = review_judgements[0].model_tag if review_judgements else "unknown"

    # 调用次数与耗时（真实 token/成本由 provider.calls_made 跟踪，阶段 3 先粗记）
    for role, p in providers.items():
        llm_calls.append(
            {
                "role": role.value,
                "provider": p.name,
                "model_tag": p.model_tag,
                "calls_made": p.calls_made,
            }
        )

    metadata = {
        "per_role": {
            "fact_reviewer": [j.model_dump() for j in fact_judgements],
            "evidence_reviewer": [j.model_dump() for j in ev_judgements],
            "independent_reviewer": [j.model_dump() for j in review_judgements],
        },
        "llm_calls": llm_calls,
        "model_tags": model_tags,
        "total_latency_s": round(time.time() - started, 3),
    }
    return {"judgements": all_judgements, "metadata": metadata}
