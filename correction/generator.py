"""修正生成器：对可修正主张生成基于证据的建议。

输入：claims + verification + evidence + LLMProvider（可选，live 时提供）
输出：List[Correction]
设计理由：
- 可修正条件：状态 ∈ {INSUFFICIENT, PARTIAL, CONTRADICTED} 且 有证据关联。
- UNVERIFIABLE / VERIFIED 不生成修正。
- LLM 失败 → 返回带标记的降级 Correction（suggested_text 为空 + reason 说明），不编造。
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from core.enums import ClaimStatus
from core.models import Claim, Correction, Evidence, VerificationResult
from models.base import LLMProvider

SYSTEM_CORRECT = (
    "你是 VeriMind AI 的修正助手。请基于提供的证据，对指定主张生成修正建议。"
    "规则：保留原文中已被证据支持的部分；仅修改有证据支持需要修改的内容；"
    "无法核验的部分可删除、弱化表述或标注不确定性；不得编造证据。"
    "输出 JSON：{\"suggested_text\":\"...\",\"reason\":\"...\",\"preserved_parts\":[...]}"
)


def _is_correctable(status: ClaimStatus) -> bool:
    return status in (
        ClaimStatus.INSUFFICIENT,
        ClaimStatus.PARTIAL,
        ClaimStatus.CONTRADICTED,
    )


def generate_corrections(
    claims: List[Claim],
    verification: List[VerificationResult],
    evidence: List[Evidence],
    provider: Optional[LLMProvider] = None,
) -> List[Correction]:
    """对可修正主张生成修正建议列表。"""
    ev_by_id = {e.id: e for e in evidence}
    out: List[Correction] = []

    for vr in verification:
        if not _is_correctable(vr.status):
            continue
        claim = next((c for c in claims if c.id == vr.claim_id), None)
        if claim is None:
            continue
        related_ev = [ev_by_id[eid] for eid in vr.evidence_ids if eid in ev_by_id]

        if provider is not None:
            # live：LLM 生成
            prompt = (
                f"原文主张：{claim.normalized}\n"
                f"原文片段：{claim.original_snippet}\n"
                f"证据：{json.dumps([e.model_dump(mode='json') for e in related_ev], ensure_ascii=False)}\n"
                f"判定状态：{vr.status.value}\n"
                f"判定理由：{vr.rationale}\n\n请生成修正建议。"
            )
            resp = provider.complete(prompt, system=SYSTEM_CORRECT, json_mode=True)
            if resp.ok and resp.parsed:
                parsed: Dict[str, Any] = resp.parsed
                suggested = parsed.get("suggested_text", "")
                if not isinstance(suggested, str):
                    suggested = json.dumps(suggested, ensure_ascii=False)
                reason = parsed.get("reason", "")
                if not isinstance(reason, str):
                    reason = json.dumps(reason, ensure_ascii=False)
                preserved = parsed.get("preserved_parts", [])
                if not isinstance(preserved, list):
                    preserved = [str(preserved)]
                out.append(
                    Correction(
                        claim_id=claim.id,
                        original_text=claim.original_snippet,
                        suggested_text=suggested[:500],
                        reason=reason[:500],
                        evidence_ids=vr.evidence_ids,
                        preserved_parts=preserved[:5],
                    )
                )
            else:
                # LLM 失败 → 降级占位，明确标注
                out.append(
                    Correction(
                        claim_id=claim.id,
                        original_text=claim.original_snippet,
                        suggested_text="",
                        reason=f"（模拟/降级）LLM 修正调用失败：{resp.error}；需人工依据证据 {vr.evidence_ids} 修正。",
                        evidence_ids=vr.evidence_ids,
                        preserved_parts=[],
                    )
                )
        else:
            # 无 provider（stub）：占位修正，明确标注需人工
            out.append(
                Correction(
                    claim_id=claim.id,
                    original_text=claim.original_snippet,
                    suggested_text="",
                    reason=(
                        f"（离线桩）检测到证据 {vr.evidence_ids} 支持部分修改，"
                        "但无 LLM 可用，未生成自动修正文本；需人工依据上述证据修改，"
                        f"判定：{vr.status.value}。"
                    ),
                    evidence_ids=vr.evidence_ids,
                    preserved_parts=[],
                )
            )

    return out
