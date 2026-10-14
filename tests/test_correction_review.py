"""阶段 5 测试：修正生成 + 独立复核（离线桩 / 确定性路径）。"""
from correction.generator import generate_corrections
from core.enums import ClaimStatus, ClaimType
from core.models import Claim, Evidence, VerificationResult
from review.reviewer import review_corrections
from datetime import datetime, timezone


def _claim(cid="C001") -> Claim:
    return Claim(id=cid, original_snippet="准确率提高 40%", normalized="准确率提高 40%", type=ClaimType.NUMERIC)


def _vr(status: ClaimStatus, cid="C001") -> VerificationResult:
    return VerificationResult(claim_id=cid, status=status, rationale="test", evidence_ids=[])


def _ev(eid="E1") -> Evidence:
    return Evidence(id=eid, source_name="OpenAlex", url="https://example.com", title="T", retrieved_at=datetime.now(timezone.utc))


def test_no_correction_for_verified():
    """已核实 / 暂无法核验 的主张不生成修正。"""
    c = [_claim()]
    assert generate_corrections(c, [_vr(ClaimStatus.VERIFIED)], [_ev()]) == []
    assert generate_corrections(c, [_vr(ClaimStatus.UNVERIFIABLE)], []) == []


def test_stub_correction_placeholder():
    """无 LLM（provider=None）→ 占位修正：suggested_text 空 + 明确标注离线桩。"""
    c = [_claim()]
    corr = generate_corrections(c, [_vr(ClaimStatus.INSUFFICIENT)], [_ev()])
    assert len(corr) == 1
    assert corr[0].suggested_text == ""
    assert "离线桩" in corr[0].reason or "人工" in corr[0].reason
    assert corr[0].evidence_ids == []


def test_stub_review_fails_on_empty_suggested():
    """桩修正 suggested_text 为空 → 复核 passed=False，resolved=False。"""
    c = [_claim()]
    corr = generate_corrections(c, [_vr(ClaimStatus.INSUFFICIENT)], [_ev()])
    review = review_corrections(corr, c, [_vr(ClaimStatus.INSUFFICIENT)], [_ev()], provider=None)
    assert len(review) == 1
    assert review[0].passed is False
    assert review[0].resolved_original_issue is False


def test_review_does_not_crash_on_no_corrections():
    """无修正时复核返回空列表，不崩。"""
    assert review_corrections([], [_claim()], [_vr(ClaimStatus.VERIFIED)], [_ev()], provider=None) == []


def test_review_result_json_safe():
    """ReviewResult 必须可 JSON 序列化。"""
    import json
    c = [_claim()]
    corr = generate_corrections(c, [_vr(ClaimStatus.CONTRADICTED)], [_ev()])
    review = review_corrections(corr, c, [_vr(ClaimStatus.CONTRADICTED)], [_ev()], provider=None)
    json.dumps([r.model_dump(mode="json") for r in review], ensure_ascii=False)
