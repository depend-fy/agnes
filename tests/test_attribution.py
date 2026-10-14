"""问题分类器测试（修复版：无证据≠错误，保守判定）。

旧行为（已修掉）：无证据就贴 CITATION_NOT_EXIST/NUMERIC_ERROR/OVERREACH_LOGIC。
新行为：无证据 = UNVERIFIABLE + 中性"缺少必要证据"，等待核实，不贴否定标签。
"""
from attribution.classifier import classify
from claims.extractor import extract
from core.enums import ClaimStatus, ClaimType, IssueType


def test_no_evidence_gives_unverifiable():
    claims = extract("某研究 DOI 为 10.1/abc，准确率提高 40%。")
    results = classify(claims, [])
    for r in results:
        assert r.status == ClaimStatus.UNVERIFIABLE
        assert r.evidence_ids == []


def test_no_evidence_no_negative_labels():
    """无证据时不贴否定标签（引用不存在/数字错误/逻辑过度），只贴中性"缺少必要证据"。"""
    claims = extract("某研究 DOI 为 10.1/abc，准确率提高 40%，证明有效。")
    results = classify(claims, [])
    for r in results:
        assert IssueType.CITATION_NOT_EXIST not in r.issue_types
        assert IssueType.NUMERIC_ERROR not in r.issue_types
        assert IssueType.OVERREACH_LOGIC not in r.issue_types
        assert IssueType.MISSING_EVIDENCE in r.issue_types


def test_doi_metadata_flags_citation_issue_only_when_checked():
    """CITATION_NOT_EXIST 仅在 DOI 被精确查证且确实查无（checked_dois）时才给。"""
    claims = extract("某研究 DOI 为 10.1/abc。")
    # 未查证（默认）→ 不贴
    r1 = classify(claims, [])
    assert all(IssueType.CITATION_NOT_EXIST not in x.issue_types for x in r1)
    # 查证且查无 → 贴
    r2 = classify(claims, [], checked_dois={"10.1/abc"})
    assert any(IssueType.CITATION_NOT_EXIST in x.issue_types for x in r2)


def test_numeric_no_evidence_neutral():
    """数字主张无证据 → UNVERIFIABLE + 中性标签（不武断判数字错误）。"""
    claims = extract("准确率提高 40%。")
    results = classify(claims, [])
    assert all(r.status == ClaimStatus.UNVERIFIABLE for r in results)
    assert all(IssueType.NUMERIC_ERROR not in r.issue_types for r in results)


def test_causal_no_evidence_neutral():
    """因果主张无证据 → UNVERIFIABLE + 中性标签（不武断判逻辑过度）。"""
    claims = extract("证明该方法有效。")
    results = classify(claims, [])
    assert all(r.status == ClaimStatus.UNVERIFIABLE for r in results)
    assert all(IssueType.OVERREACH_LOGIC not in r.issue_types for r in results)


def test_rationale_mentions_pending_verification():
    claims = extract("某研究发表于 2023 年。")
    results = classify(claims, [])
    assert all("等待核实" in r.rationale or "暂无法核验" in r.rationale for r in results)
