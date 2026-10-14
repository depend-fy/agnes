"""阶段 2 测试：主张提取器。"""
from claims.extractor import extract
from core.enums import ClaimType


def test_doi_extraction():
    claims = extract("某研究 DOI 为 10.1234/abc，证明准确率提高 40%。")
    dois = [c for c in claims if c.type == ClaimType.METADATA]
    assert len(dois) >= 1
    assert any("10.1234/abc" in c.normalized for c in dois)


def test_numeric_extraction():
    claims = extract("该方法可以将准确率提高 40%。")
    nums = [c for c in claims if c.type == ClaimType.NUMERIC]
    assert len(nums) >= 1
    assert any("40" in c.normalized for c in nums)


def test_empty_text():
    assert extract("") == []
    assert extract("   ") == []


def test_general_fallback():
    claims = extract("这是一段没有任何可识别模式的纯陈述文本。")
    assert len(claims) >= 1
    assert claims[0].type == ClaimType.GENERAL


def test_claim_ids_sequential():
    claims = extract("某研究发表于 2023 年，DOI 为 10.1/abc，准确率提高 40%。")
    ids = [c.id for c in claims]
    assert ids[0] == "C001"
    # 编号连续
    assert ids == [f"C{i + 1:03d}" for i in range(len(ids))]
