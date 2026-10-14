"""报告组装：把 claims + verification 汇总为 DetectionReport。

阶段 2 最小版：只做结构汇总；corrections / review / evidence 暂为空列表（阶段 4/5 填充）。
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import List, Optional

from core.enums import ClaimStatus
from core.models import Claim, Correction, DetectionReport, Evidence, ReviewResult, VerificationResult


def assemble(
    input_text: str,
    claims: List[Claim],
    evidence: Optional[List[Evidence]] = None,
    verification: Optional[List[VerificationResult]] = None,
    corrections: Optional[List[Correction]] = None,
    review: Optional[List[ReviewResult]] = None,
) -> DetectionReport:
    evidence = evidence or []
    verification = verification or []
    corrections = corrections or []
    review = review or []

    # 未解决项：复核未通过，或状态为 UNVERIFIABLE/INSUFFICIENT/CONFLICTING_SOURCES
    unresolved = [
        f"复核未通过：{r.notes[:80]}"
        for r in review
        if not r.passed
    ]
    for r in review:
        if not r.passed:
            for e in r.introduced_new_errors:
                unresolved.append(f"修正引入新错误：{e}")
            for e in r.new_unfounded_claims:
                unresolved.append(f"新增无依据结论：{e}")
    unresolved += [
        f"{c.id}: {c.status.value}"
        for v in verification
        for c in claims
        if c.id == v.claim_id
        and v.status in (ClaimStatus.UNVERIFIABLE, ClaimStatus.INSUFFICIENT, ClaimStatus.CONFLICTING_SOURCES)
    ]

    status_counts = {s.value: 0 for s in ClaimStatus}
    for v in verification:
        status_counts[v.status.value] += 1

    return DetectionReport(
        report_id=f"RPT-{uuid.uuid4().hex[:8]}",
        input_text=input_text,
        claims=claims,
        evidence=evidence,
        verification=verification,
        corrections=corrections,
        review=review,
        unresolved=unresolved,
        metadata={
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "mode": "stub_offline",
            "claim_count": len(claims),
            "status_counts": status_counts,
        },
    )
