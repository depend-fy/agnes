"""检测管线：把各步骤串成一条端到端流程。

阶段 5 更新：
- 修正层接入 correction.generator（基于证据的修正，live 走 LLM / stub 走占位）。
- 复核层接入 review.reviewer（独立复核修正结果）。
- 修正与复核结果写入 Correction + ReviewResult，报告页展示。
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Dict, List, Optional

from attribution.classifier import classify
from claims.extractor import extract
from correction.generator import generate_corrections as gen_corrections
from core.config import get_settings
from core.enums import RoleType
from core.models import (
    Claim,
    Correction,
    DetectionReport,
    Evidence,
    ReviewResult,
    VerificationResult,
)
from models.base import LLMProvider
from models.factory import build_providers, provider_summary
from report.assembler import assemble
from retrieval.searcher import retrieve_with_meta as _retrieve_with_meta
from retrieval.snapshot import retrieve_with_fallback
from review.reviewer import review_corrections as do_review
from roles.orchestrator import run_all_roles
from metrics import build_metrics, collect_provider_stats


def run(text: str) -> DetectionReport:
    """端到端运行检测管线（检索 + 多角色 + 修正 + 复核）。"""
    started = time.time()
    settings = get_settings()

    # 1. 提取
    claims = extract(text)

    # 2. 检索（真实优先，失败/空时兜底到本地证据快照）+ 回传 checked_dois
    t_retrieval_start = time.time()
    meta_search = _retrieve_with_meta(claims)
    checked_dois = meta_search["checked_dois"]
    # live_search_fn 返回证据列表（供快照兜底）；checked_dois 只在真实检索时有效
    retrieval = retrieve_with_fallback(
        claims, live_search_fn=lambda: meta_search["evidence"]
    )
    evidence = retrieval["evidence"]
    evidence_source = retrieval["source"]
    # 快照兜底时 checked_dois 不可靠（未真实查 DOI）→ 清空，避免误贴"引用不存在"
    if evidence_source != "live":
        checked_dois = set()
    retrieval_s = round(time.time() - t_retrieval_start, 3)

    # 3. 多角色协同检测（拿到真实证据）
    providers: Dict[RoleType, LLMProvider] = build_providers(settings)
    role_result = run_all_roles(
        providers, claims, evidence, text,
        corrections=[],
        timeout_s=settings.agnes.timeout_s,
    )
    all_judgements = role_result["judgements"]
    role_metadata = role_result["metadata"]

    # 4. 分类 + 角色 judgement 挂载（基于真实证据 + checked_dois）
    verification = classify(claims, evidence, checked_dois=checked_dois)
    fact_js = [j for j in all_judgements if j.role == RoleType.FACT_REVIEWER]
    ev_js = [j for j in all_judgements if j.role == RoleType.EVIDENCE_REVIEWER]
    rev_js = [j for j in all_judgements if j.role == RoleType.INDEPENDENT_REVIEWER]
    for i, vr in enumerate(verification):
        vr.role_judgements = (
            ([fact_js[i]] if i < len(fact_js) else [])
            + ([ev_js[i]] if i < len(ev_js) else [])
            + ([rev_js[i]] if i < len(rev_js) else [])
        )

    # 5. 基于证据修正（live 走 LLM，stub 走占位）
    correction_provider: Optional[LLMProvider] = None
    if settings.mode == "live" and settings.deepseek is not None and settings.deepseek.has_key:
        correction_provider = providers[RoleType.INDEPENDENT_REVIEWER]
    corrections = gen_corrections(claims, verification, evidence, provider=correction_provider)

    # 6. 独立复核（检查修正是否解决原问题 / 是否引入新错误）
    review_provider: Optional[LLMProvider] = None
    if settings.mode == "live" and settings.deepseek is not None and settings.deepseek.has_key:
        review_provider = providers[RoleType.INDEPENDENT_REVIEWER]
    review = do_review(corrections, claims, verification, evidence, provider=review_provider)

    # 7. 汇总
    report = assemble(
        input_text=text,
        claims=claims,
        evidence=evidence,
        verification=verification,
        corrections=corrections,
        review=review,
    )
    report.metadata.update(
        {
            "started_at": datetime.now(timezone.utc).isoformat(),
            "total_pipeline_s": round(time.time() - started, 3),
            "mode": settings.mode,
            "providers": provider_summary(providers),
            "role_metadata": role_metadata,
            "evidence_count": len(evidence),
            "evidence_source": evidence_source,
            "retrieval_s": retrieval_s,
            "correction_count": len(corrections),
            "review_count": len(review),
            "review_passed": sum(1 for r in review if r.passed),
        }
    )
    # 阶段 7：成本 / 延迟 / token 统计真实入账
    provider_stats = collect_provider_stats({k: p for k, p in providers.items()})
    report.metadata["metrics"] = build_metrics(provider_stats, pipeline_s=report.metadata["total_pipeline_s"], retrieval_s=retrieval_s)
    return report
