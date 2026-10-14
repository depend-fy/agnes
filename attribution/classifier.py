"""证据-主张匹配与状态判定（修复版，贯彻"无证据≠错误"）。

核心原则（阶段 0 + 用户反馈）：
- 检索不到可信证据 → UNVERIFIABLE（暂无法核验）+ **中性**标签"缺少必要证据"，
  绝不贴"引用不存在/数字错误/逻辑过度"等**否定性**标签。
  "没搜到"不等于"不存在/是错的"，只能说明"等待核实"。
- CITATION_NOT_EXIST（引用不存在）**只在 DOI 被精确查证、且检索源明确返回查无**时给。
  这需要检索器回传 checked_dois（查过但确实没有的 DOI 集合）。
- 有证据时：
  - 摘要与主张关键数字一致 → VERIFIED
  - 摘要未确认数字 → INSUFFICIENT（证据不足，等待核实，不判"数字错误"）
  - 摘要层面未完整确认结论 → PARTIAL（文献真实 ≠ 结论被证实）
- 明确"元数据存在 ≠ 支持结论"。
"""
from __future__ import annotations

import re
from typing import List, Optional, Set

from core.enums import ClaimStatus, ClaimType, IssueType
from core.models import Claim, Evidence, VerificationResult


def _extract_numeric(normalized: str) -> List[str]:
    """提取主张中的数字（用于与证据摘要比对）。

    收紧（避免误判）：
    - 排除 4 位年份（19xx/20xx），年份不等于事实支持。
    - 只保留有判别力的数字（比例、精度、量级等）。
    """
    raw = re.findall(r"\d+(?:\.\d+)?", normalized or "")
    nums: List[str] = []
    for n in raw:
        # 排除纯 4 位年份 1900-2099
        if re.fullmatch(r"(19|20)\d{2}", n):
            continue
        nums.append(n)
    return nums


def _extract_doi(snippet: str, normalized: str) -> str:
    """从主张里提取 DOI（供判定"查无此 DOI"时区分 METADATA 主张）。"""
    m = re.search(r"\b([0-9]{1,3}\.[0-9]{0,12}/[^\s,;，。]+)\b", snippet or "")
    if m:
        return m.group(1)
    m2 = re.search(r"\b([0-9]{1,3}\.[0-9]{0,12}/[^\s,;，。]+)\b", normalized or "")
    return m2.group(1) if m2 else ""


def classify(
    claims: List[Claim],
    evidence: List[Evidence],
    checked_dois: Optional[Set[str]] = None,
) -> List[VerificationResult]:
    """对每条主张，结合证据做状态判定。

    checked_dois: 检索器实际查过但"确实没有"的 DOI 集合（大小写不敏感）。
      仅当某 METADATA 主张的 DOI 在此集合内，才判 CITATION_NOT_EXIST。
      默认空集合 → 永不贴"引用不存在"（保守）。
    """
    checked_dois = {d.lower() for d in (checked_dois or set())}
    # 建立 claim -> evidence 索引
    ev_by_claim: dict[str, List[Evidence]] = {c.id: [] for c in claims}
    for ev in evidence:
        for cid in ev.supports:
            if cid in ev_by_claim:
                ev_by_claim[cid].append(ev)

    results: List[VerificationResult] = []
    for c in claims:
        evs = ev_by_claim.get(c.id, [])
        issue_types: List[IssueType] = []
        rationale_parts: List[str] = []

        if not evs:
            # 无证据：统一 UNVERIFIABLE + 中性"缺少必要证据"，不贴否定标签
            status = ClaimStatus.UNVERIFIABLE
            issue_types.append(IssueType.MISSING_EVIDENCE)
            rationale_parts.append(
                f"检索未找到支持「{c.normalized}」的可信证据，标记为暂无法核验（等待核实）。"
                "无证据不等于错误，需扩大检索范围或人工核验。"
            )
            # 仅当 DOI 被精确查证且源明确查无 → 才升级为"引用不存在"
            claim_doi = _extract_doi(c.original_snippet, c.normalized)
            if c.type == ClaimType.METADATA and claim_doi and claim_doi.lower() in checked_dois:
                issue_types.append(IssueType.CITATION_NOT_EXIST)
                rationale_parts.append(
                    f"DOI「{claim_doi}」已精确查证，检索源明确返回查无此 DOI，标记为引用不存在。"
                )
        else:
            # 有证据
            # 阶段 8：按证据来源等级保守化判定
            academic_evs = [ev for ev in evs if ev.source_tier in ("academic", "wikipedia")]
            web_evs = [ev for ev in evs if ev.source_tier == "web"]
            key_numbers = _extract_numeric(c.normalized)
            if key_numbers:
                # 多数字主张要求全部匹配（避免年份/无关数字命中就误升级）
                all_matched_academic = all(
                    any(num in (ev.snippet or "") for ev in academic_evs) for num in key_numbers
                ) if academic_evs else False
                if all_matched_academic:
                    status = ClaimStatus.VERIFIED
                    rationale_parts.append(
                        f"找到 {len(academic_evs)} 条学术/权威证据，摘要层面与主张的关键数字 {key_numbers} "
                        "全部一致，标记为已核实。"
                    )
                else:
                    # 有数字但摘要未全部确认 → 证据不足（等待核实），不判"数字错误"
                    status = ClaimStatus.INSUFFICIENT
                    issue_types.append(IssueType.MISSING_EVIDENCE)
                    if web_evs and not academic_evs:
                        status = ClaimStatus.PARTIAL
                        rationale_parts.append(
                            f"仅检索到 {len(web_evs)} 条普通网页证据（低质来源，仅供参考），"
                            f"未找到学术证据确认关键数字 {key_numbers}，标记为部分支持（证据有限，待核实）。"
                        )
                    else:
                        rationale_parts.append(
                            f"找到 {len(academic_evs)} 条学术/权威证据，但摘要未全部支持主张中的关键数字 {key_numbers}，"
                            "标记为证据不足（等待核实，需查看原文确认，不判定为数字错误）。"
                        )
            else:
                if academic_evs:
                    status = ClaimStatus.PARTIAL
                    rationale_parts.append(
                        f"找到 {len(academic_evs)} 条学术/权威证据支持文献存在，但摘要层面未完整确认主张结论，"
                        "标记为部分支持（文献真实 ≠ 结论被证实）。"
                    )
                elif web_evs:
                    # 仅有普通网页证据 → 顶多部分支持，标注低质来源，不升级已核实
                    status = ClaimStatus.PARTIAL
                    issue_types.append(IssueType.MISSING_EVIDENCE)
                    rationale_parts.append(
                        f"仅检索到 {len(web_evs)} 条普通网页证据（低质来源，仅供参考），"
                        "未找到学术证据，标记为部分支持（证据有限，待核实，不判定为已核实）。"
                    )
                else:
                    status = ClaimStatus.PARTIAL
                    rationale_parts.append(
                        f"找到 {len(evs)} 条证据支持文献存在，但摘要层面未完整确认主张结论，"
                        "标记为部分支持（文献真实 ≠ 结论被证实）。"
                    )
            if c.type == ClaimType.METADATA and not key_numbers:
                issue_types.append(IssueType.MISSING_EVIDENCE)

        rationale = " ".join(rationale_parts) or "未提供判定理由"

        results.append(
            VerificationResult(
                claim_id=c.id,
                status=status,
                issue_types=issue_types,
                rationale=rationale,
                evidence_ids=[ev.id for ev in evs],
                role_judgements=[],  # 由 pipeline 挂载
            )
        )
    return results
