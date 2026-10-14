"""阶段 6 测试：边界与失败场景（错误输入 / API 失败 / 修正引入新错误）。

设计理由：
- 这些场景保证"现场演示不出丑"：任何一步失败都有确定行为，不崩、不编造。
- 用 monkeypatch / 直接构造 替代真实网络，保证离线可复现。
"""
from typing import List

import pytest

from claims.extractor import extract
from correction.generator import generate_corrections
from core.enums import ClaimStatus, ClaimType
from core.models import Claim, Evidence, ReviewResult, VerificationResult
from review.reviewer import review_corrections
from models.base import LLMProvider, LLMResponse
from datetime import datetime, timezone


# ---------- 错误输入 ----------

def test_extract_empty_and_whitespace():
    assert extract("") == []
    assert extract("   \n\t  ") == []


def test_extract_single_char_not_crash():
    # 单字符文本走 GENERAL 兜底，不崩
    claims = extract("中")
    assert len(claims) >= 1
    assert claims[0].type in (ClaimType.GENERAL, ClaimType.EXISTENCE)


# ---------- API 失败（provider 返回错误）----------

class _FailingProvider(LLMProvider):
    """模拟 LLM 调用失败的 provider。"""
    name = "fail"
    model_tag = "fail_model"
    calls_made = 0

    def complete(self, prompt, system="", json_mode=False, timeout_s=60.0):
        self.calls_made += 1
        return LLMResponse(model_tag="fail_model", provider="fail", error="simulated 500")


def test_correction_degrades_on_llm_failure():
    """LLM 失败 → 修正降级为占位（suggested_text 空 + 明确标注），不崩、不编造。"""
    c = [Claim(id="C001", original_snippet="准确率提高 40%", normalized="准确率提高 40%", type=ClaimType.NUMERIC)]
    vr = [VerificationResult(claim_id="C001", status=ClaimStatus.INSUFFICIENT, rationale="test", evidence_ids=[]) ]
    provider = _FailingProvider()
    corr = generate_corrections(c, vr, [], provider=provider)
    assert len(corr) == 1
    assert corr[0].suggested_text == ""
    assert "失败" in corr[0].reason or "降级" in corr[0].reason or "需人工" in corr[0].reason


def test_review_degrades_on_llm_failure():
    """LLM 失败 → 复核走确定性桩，不崩。"""
    c = [Claim(id="C001", original_snippet="准确率提高 40%", normalized="准确率提高 40%", type=ClaimType.NUMERIC)]
    vr = [VerificationResult(claim_id="C001", status=ClaimStatus.INSUFFICIENT, rationale="test", evidence_ids=[]) ]
    corr = generate_corrections(c, vr, [], provider=_FailingProvider())
    review = review_corrections(corr, c, vr, [], provider=_FailingProvider())
    assert len(review) == 1
    assert review[0].passed is False  # 占位修正 → 复核未通过


# ---------- 修正引入新错误（复核应识别）----------

def test_review_flags_unfounded_new_claim():
    """构造一条"修正在无证据下新增了无依据结论"的 ReviewResult，
    验证数据结构与组装正确记录，供报告展示。"""
    rv = ReviewResult(
        correction_id=None,
        passed=False,
        resolved_original_issue=False,
        verdict="fail",
        introduced_new_errors=["修正引入了无证据的'提高 90%'说法"],
        new_unfounded_claims=["新方法在数据集 B 上也有效（无证据）"],
        notes="修正超出证据范围，引入新无依据结论。",
    )
    # 序列化不崩
    dumped = rv.model_dump(mode="json")
    assert dumped["passed"] is False
    assert len(dumped["introduced_new_errors"]) == 1
    assert len(dumped["new_unfounded_claims"]) == 1


def test_review_pass_on_valid_correction_data():
    """有修正文本 + 复核通过时，ReviewResult 正确表达。"""
    rv = ReviewResult(
        correction_id=None,
        passed=True,
        resolved_original_issue=True,
        verdict="pass",
        introduced_new_errors=[],
        new_unfounded_claims=[],
        notes="修正合理，基于证据弱化数字表述。",
    )
    assert rv.passed is True
    assert rv.model_dump(mode="json")["verdict"] == "pass"
