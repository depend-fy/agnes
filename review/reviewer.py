"""独立复核员：对修正结果做二次检查。

输入：corrections + claims + verification + evidence + LLMProvider（可选）
输出：List[ReviewResult]
设计理由：
- 桩模式（无 LLM）做确定性检查：
  - suggested_text 为空 → 未真正修正，passed=False，resolved_original_issue=False。
  - 有文本但 reason 含"模拟/降级" → 标记为需人工。
  - 其它情况 passed=True（保守：不武断判引入新错误，只提示）。
- live 模式：LLM 检查修正是否解决原问题、是否引入新错误。
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from core.enums import ReviewVerdict
from core.models import Claim, Correction, Evidence, ReviewResult, VerificationResult
from models.base import LLMProvider

SYSTEM_REVIEW = (
    "你是 VeriMind AI 的独立复核员。请检查给定的修正建议是否：1) 解决了原始问题；"
    "2) 是否有证据支持；3) 是否引入新的事实错误；4) 是否有新的无依据结论。"
    "输出 JSON：{\"passed\":true|false,\"resolved_original_issue\":true|false,"
    "\"introduced_new_errors\":[...],\"new_unfounded_claims\":[...],\"notes\":\"...\"}"
)


def _deterministic_review(c: Correction) -> ReviewResult:
    """无 LLM 时的确定性复核。"""
    is_placeholder = "模拟" in c.reason or "降级" in c.reason or "离线桩" in c.reason
    if not c.suggested_text:
        return ReviewResult(
            correction_id=None,
            verdict=ReviewVerdict.FAIL,
            passed=False,
            resolved_original_issue=False,
            introduced_new_errors=[],
            new_unfounded_claims=[],
            notes=(
                "修正建议为空（离线桩或 LLM 未生成）；原始问题未解决，"
                "需人工依据证据修正。" + ("（已标注为模拟/降级）" if is_placeholder else "")
            ),
        )
    # 有建议文本且非占位：保守通过，提示需人工确认
    return ReviewResult(
        correction_id=None,
        verdict=ReviewVerdict.PASS if not is_placeholder else ReviewVerdict.FAIL,
        passed=not is_placeholder,
        resolved_original_issue=not is_placeholder,
        introduced_new_errors=[],
        new_unfounded_claims=[],
        notes=(
            "（桩）修正建议已生成；未做真实独立复核，需人工确认修正是否符合证据。"
            if not is_placeholder
            else "（桩/降级）修正建议为占位，未真正解决问题。"
        ),
    )


def review_corrections(
    corrections: List[Correction],
    claims: List[Claim],
    verification: List[VerificationResult],
    evidence: List[Evidence],
    provider: Optional[LLMProvider] = None,
) -> List[ReviewResult]:
    """对每条修正做独立复核。"""
    out: List[ReviewResult] = []
    for c in corrections:
        claim = next((cl for cl in claims if cl.id == c.claim_id), None)
        vr = next((v for v in verification if v.claim_id == c.claim_id), None)

        if provider is not None and c.suggested_text:
            prompt = (
                f"原始主张：{claim.normalized if claim else c.original_text}\n"
                f"原状态：{vr.status.value if vr else 'unknown'}\n"
                f"原文：{c.original_text}\n"
                f"修正建议：{c.suggested_text}\n"
                f"修改理由：{c.reason}\n"
                f"关联证据：{json.dumps([e.model_dump(mode='json') for e in evidence if e.id in c.evidence_ids], ensure_ascii=False)}\n"
            )
            resp = provider.complete(prompt, system=SYSTEM_REVIEW, json_mode=True)
            if resp.ok and resp.parsed:
                p: Dict[str, Any] = resp.parsed
                out.append(
                    ReviewResult(
                        correction_id=None,
                        verdict=ReviewVerdict.PASS if p.get("passed") else ReviewVerdict.FAIL,
                        passed=bool(p.get("passed", False)),
                        resolved_original_issue=bool(p.get("resolved_original_issue", False)),
                        introduced_new_errors=p.get("introduced_new_errors", []) or [],
                        new_unfounded_claims=p.get("new_unfounded_claims", []) or [],
                        notes=str(p.get("notes", ""))[:500],
                    )
                )
            else:
                out.append(_deterministic_review(c))
        else:
            out.append(_deterministic_review(c))

    return out
