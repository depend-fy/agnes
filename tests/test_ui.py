"""UI 视图逻辑测试（阶段 7/8 界面优化：可信度评分 / 共识 / 颜色语义 / 导出）。

设计理由：
- ui/ 是纯函数层，测试不需要 Streamlit，离线可跑。
- 重点回归保护"不编造"原则：无主张时 score=0、共识无判断=证据不足、
  导出报告不产生未标注的数字。
"""
from core.enums import ClaimStatus, IssueType, RoleType
from core.models import (
    Claim,
    Correction,
    DetectionReport,
    Evidence,
    ReviewResult,
    RoleJudgement,
    VerificationResult,
)
from datetime import datetime, timezone
from ui import (
    cautious_rewrite,
    consensus_level,
    evidence_chain,
    export_report_markdown,
    overall_confidence,
    status_color,
    status_label_zh,
    COLOR_GREEN,
    COLOR_RED,
    COLOR_GRAY,
    COLOR_YELLOW,
)


# ---------- 颜色语义 ----------

def test_status_colors_follow_semantics():
    """绿=已核实 / 红=矛盾 / 黄=部分支持、证据不足 / 灰=暂无法核验。"""
    assert status_color(ClaimStatus.VERIFIED) == COLOR_GREEN
    assert status_color(ClaimStatus.CONTRADICTED) == COLOR_RED
    assert status_color(ClaimStatus.CONFLICTING_SOURCES) == COLOR_RED
    assert status_color(ClaimStatus.PARTIAL) == COLOR_YELLOW
    assert status_color(ClaimStatus.INSUFFICIENT) == COLOR_YELLOW
    assert status_color(ClaimStatus.UNVERIFIABLE) == COLOR_GRAY
    assert status_color(ClaimStatus.UNVERIFIED) == COLOR_GRAY


def test_status_labels_zh():
    assert status_label_zh(ClaimStatus.VERIFIED) == "已核实"
    assert status_label_zh(ClaimStatus.UNVERIFIABLE) == "暂无法核验"


# ---------- 整体可信度 ----------

def _ver(status, claim_id="C1"):
    return VerificationResult(
        claim_id=claim_id, status=status, issue_types=[], rationale="t", evidence_ids=[], role_judgements=[]
    )


def test_confidence_empty():
    c = overall_confidence([])
    assert c["score"] == 0
    assert c["band"] == "none"
    assert c["band_label"] == "无可核验主张"


def test_confidence_all_verified_high():
    v = [_ver(ClaimStatus.VERIFIED, f"C{i}") for i in range(3)]
    c = overall_confidence(v)
    assert c["band"] == "high"
    assert c["band_color"] == COLOR_GREEN
    assert c["score"] >= 70


def test_confidence_contradiction_low_red():
    v = [_ver(ClaimStatus.VERIFIED, "C1"), _ver(ClaimStatus.CONTRADICTED, "C2")]
    c = overall_confidence(v)
    assert c["band"] == "low"
    assert c["band_color"] == COLOR_RED
    assert "矛盾" in c["band_label"] or "冲突" in c["band_label"]


def test_confidence_unverifiable_gray_low():
    v = [_ver(ClaimStatus.UNVERIFIABLE, "C1")]
    c = overall_confidence(v)
    assert c["band"] in ("low", "medium")
    # 无证据无矛盾 → 灰/黄，不武断判错
    assert c["band_color"] in (COLOR_GRAY, COLOR_YELLOW)


def test_confidence_no_fabricated_probability():
    """可信度是 0-100 整数（覆盖度），不是 0.0-1.0 的概率。"""
    c = overall_confidence([_ver(ClaimStatus.VERIFIED, "C1")])
    assert isinstance(c["score"], int)
    assert 0 <= c["score"] <= 100


# ---------- 多模型共识 ----------

def _role_js(role, text, tag="m"):
    return RoleJudgement(role=role, judgement=text, confidence_note="n", model_tag=tag)


def test_consensus_no_judgements_insufficient():
    ver = _ver(ClaimStatus.UNVERIFIABLE)
    c = consensus_level(ver)
    assert c["level"] == "insufficient"
    assert c["color"] == COLOR_GRAY


def test_consensus_divergence():
    ver = _ver(ClaimStatus.CONTRADICTED)
    ver.role_judgements = [
        _role_js(RoleType.FACT_REVIEWER, "该主张成立"),
        _role_js(RoleType.EVIDENCE_REVIEWER, "证据不足，无法判定"),
    ]
    c = consensus_level(ver)
    assert c["level"] == "low"
    assert c["color"] == COLOR_RED
    assert c["label"] == "存在分歧"
    assert "fact_reviewer" in c["divergent_roles"]
    assert "evidence_reviewer" in c["divergent_roles"]


def test_consensus_high():
    ver = _ver(ClaimStatus.VERIFIED)
    ver.role_judgements = [
        _role_js(RoleType.FACT_REVIEWER, "主张成立，摘要一致"),
        _role_js(RoleType.EVIDENCE_REVIEWER, "证据支持该结论"),
    ]
    c = consensus_level(ver)
    assert c["level"] == "high"
    assert c["color"] == COLOR_GREEN
    assert c["label"] == "高度一致"


def test_consensus_insufficient_evidence():
    ver = _ver(ClaimStatus.INSUFFICIENT)
    ver.role_judgements = [
        _role_js(RoleType.EVIDENCE_REVIEWER, "证据不足，无法判定")
    ]
    c = consensus_level(ver)
    assert c["level"] == "insufficient"
    assert c["color"] == COLOR_GRAY


# ---------- 证据链 ----------

def test_evidence_chain_steps():
    from core.enums import ClaimType
    c = Claim(id="C1", original_snippet="准确率提高 40%", normalized="准确率提高 40%", type=ClaimType.NUMERIC)
    ev = [Evidence(
        id="E1", source_name="Crossref", url="https://doi.org/x", title="Paper T",
        authors=["A"], year=2023, doi="10.1/x",
        retrieved_at=datetime.now(timezone.utc), snippet="abstract mentions 40%", supports=["C1"]
    )]
    ver = _ver(ClaimStatus.VERIFIED, "C1")
    ver.evidence_ids = ["E1"]
    chain = evidence_chain(c, ver, ev)
    steps = [s["step"] for s in chain]
    assert "论断" in steps
    assert "关键词" in steps
    assert "检索论文" in steps
    assert "原文依据" in steps
    assert "多模型结论" in steps
    # 检索论文那步应有 url/year
    paper_step = next(s for s in chain if s["step"] == "检索论文")
    assert paper_step["url"] == "https://doi.org/x"
    assert paper_step["year"] == 2023


def test_evidence_chain_no_evidence():
    from core.enums import ClaimType
    c = Claim(id="C1", original_snippet="X", normalized="X", type=ClaimType.GENERAL)
    ver = _ver(ClaimStatus.UNVERIFIABLE, "C1")
    chain = evidence_chain(c, ver, [])
    steps = [s["step"] for s in chain]
    assert "多模型结论" in steps
    # 无证据时不应有"检索论文"步骤
    assert "检索论文" not in steps


# ---------- 谨慎改写 ----------

def test_cautious_rewrite():
    assert "证明" not in cautious_rewrite("本文证明该方法有效")
    assert "现有证据提示" in cautious_rewrite("本文证明该方法有效")
    # 无强词时不变
    assert cautious_rewrite("该方法有效") == "该方法有效"


# ---------- 导出 ----------

def _report() -> DetectionReport:
    ev = [Evidence(
        id="E1", source_name="Crossref", url="https://doi.org/x", title="Paper T",
        retrieved_at=datetime.now(timezone.utc), snippet="abstract 40%", supports=["C1"]
    )]
    c1 = Claim(id="C1", original_snippet="准确率提高 40%", normalized="准确率提高 40%")
    ver = _ver(ClaimStatus.VERIFIED, "C1")
    ver.evidence_ids = ["E1"]
    corr = Correction(claim_id="C1", original_text="准确率提高 40%", suggested_text="现有研究提示准确率有所提升", reason="t", evidence_ids=["E1"])
    return DetectionReport(
        report_id="RPT-test",
        input_text="准确率提高 40%。",
        claims=[c1],
        evidence=ev,
        verification=[ver],
        corrections=[corr],
        review=[],
        unresolved=[],
        metadata={"generated_at": "2026-01-01", "mode": "test", "claim_count": 1},
    )


def test_export_markdown_sections():
    md = export_report_markdown(_report())
    assert "原文" in md
    assert "风险论断" in md or "论断" in md
    assert "模型共识" in md
    assert "建议改写" in md
    assert "https://doi.org/x" in md  # 证据可追溯
    assert "40" in md
    # 不编造：无"概率"伪精确数字
    assert "0.95" not in md and "95%" not in md


def test_export_markdown_no_evidence_claim():
    c1 = Claim(id="C9", original_snippet="X", normalized="X")
    ver = _ver(ClaimStatus.UNVERIFIABLE, "C9")
    rpt = DetectionReport(
        report_id="RPT-x", input_text="X", claims=[c1], evidence=[],
        verification=[ver], corrections=[], review=[], unresolved=[],
        metadata={"mode": "t"}
    )
    md = export_report_markdown(rpt)
    # 无证据时仍要说明"不等于错误"
    assert "不等于" in md or "未找到" in md or "暂无法" in md
