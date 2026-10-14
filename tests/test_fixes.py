"""修复测试：判定保守化（无证据≠错误）+ 检索多源召回 + checked_dois。

核心回归保护：
- 无证据 → UNVERIFIABLE + 中性"缺少必要证据"，绝不贴 CITATION_NOT_EXIST/
  NUMERIC_ERROR/OVERREACH_LOGIC 等否定标签（除非 DOI 被查证确实查无）。
- 检索器多源并发（Crossref+OpenAlex），提高召回。
"""
from unittest.mock import patch

from attribution.classifier import classify
from claims.extractor import extract
from core.enums import ClaimStatus, ClaimType, IssueType
from core.models import Claim
from retrieval.searcher import _extract_keywords, retrieve_with_meta


# ---------- 修复 1：无证据 = 中性标签 ----------

def test_no_evidence_is_neutral_not_negative():
    """无证据时不应贴否定标签（引用不存在/数字错误/逻辑过度）。"""
    claims = extract("某研究 DOI 为 10.1/abc，准确率提高 40%，证明有效。")
    results = classify(claims, [])
    for r in results:
        assert r.status == ClaimStatus.UNVERIFIABLE
        # 否定标签不应出现
        assert IssueType.CITATION_NOT_EXIST not in r.issue_types
        assert IssueType.NUMERIC_ERROR not in r.issue_types
        assert IssueType.OVERREACH_LOGIC not in r.issue_types
        # 中性标签应在
        assert IssueType.MISSING_EVIDENCE in r.issue_types
        # 理由应写"等待核实/暂无法核验"
        assert "等待核实" in r.rationale or "暂无法核验" in r.rationale


def test_citation_not_exist_only_when_checked_doi():
    """仅当 DOI 被精确查证且确实查无（checked_dois）才贴引用不存在。"""
    claims = extract("某研究 DOI 为 10.1/abc。")
    # 不传 checked_dois → 永不贴
    r1 = classify(claims, [])
    assert all(IssueType.CITATION_NOT_EXIST not in x.issue_types for x in r1)
    # 传入查无的 DOI → 该 METADATA 主张贴 CITATION_NOT_EXIST
    r2 = classify(claims, [], checked_dois={"10.1/abc"})
    assert any(IssueType.CITATION_NOT_EXIST in x.issue_types for x in r2)

def test_evidence_insufficient_not_numeric_error():
    """有证据但摘要未确认数字 → INSUFFICIENT + 中性标签，不判数字错误。"""
    c = [Claim(id="C001", original_snippet="准确率提高 40%", normalized="准确率提高 40%", type=ClaimType.NUMERIC)]
    from core.models import Evidence
    from datetime import datetime, timezone
    # 证据的 supports 必须指向该 claim，否则 classify 视为"无证据"分支
    ev = [Evidence(id="E1", source_name="OpenAlex", url="http://x", title="T",
                   retrieved_at=datetime.now(timezone.utc), snippet="some abstract",
                   supports=["C001"])]
    results = classify(c, ev)
    assert results[0].status == ClaimStatus.INSUFFICIENT
    assert IssueType.NUMERIC_ERROR not in results[0].issue_types
    assert IssueType.MISSING_EVIDENCE in results[0].issue_types


def test_numeric_year_excluded_from_matching():
    """年份 19xx/20xx 不参与数字匹配（避免误判）。"""
    c = [Claim(id="C001", original_snippet="2023 年方法把精度提到 90%",
               normalized="2023 年方法把精度提到 90%", type=ClaimType.NUMERIC)]
    from core.models import Evidence
    from datetime import datetime, timezone
    # 摘要只含 2023，不含 90 → 不应 VERIFIED
    ev = [Evidence(id="E1", source_name="OpenAlex", url="http://x", title="T",
                   retrieved_at=datetime.now(timezone.utc),
                   snippet="published in 2023 we show a method", supports=["C001"])]
    r = classify(c, ev)
    assert r[0].status != ClaimStatus.VERIFIED


def test_all_numbers_must_match_for_verified():
    """多数字主张要求全部匹配才算 VERIFIED（任一不中 → INSUFFICIENT）。"""
    c = [Claim(id="C001", original_snippet="方法把 A 提到 90%，B 提到 40%",
               normalized="方法把 A 提到 90%，B 提到 40%", type=ClaimType.NUMERIC)]
    from core.models import Evidence
    from datetime import datetime, timezone
    ev = [Evidence(id="E1", source_name="OpenAlex", url="http://x", title="T",
                   retrieved_at=datetime.now(timezone.utc),
                   snippet="A reaches 90% but B result not reported", supports=["C001"])]
    r = classify(c, ev)
    # 90 命中但 40 不命中 → 不能 VERIFIED
    assert r[0].status == ClaimStatus.INSUFFICIENT
    assert IssueType.NUMERIC_ERROR not in r[0].issue_types


def test_all_numbers_matched_gives_verified():
    c = [Claim(id="C001", original_snippet="方法把 A 提到 90%，B 提到 40%",
               normalized="方法把 A 提到 90%，B 提到 40%", type=ClaimType.NUMERIC)]
    from core.models import Evidence
    from datetime import datetime, timezone
    ev = [Evidence(id="E1", source_name="OpenAlex", url="http://x", title="T",
                   retrieved_at=datetime.now(timezone.utc),
                   snippet="A reaches 90%, B reaches 40%", supports=["C001"])]
    r = classify(c, ev)
    assert r[0].status == ClaimStatus.VERIFIED


# ---------- 修复 2A：关键词抽取 + 多源召回 ----------

def test_extract_keywords_english_and_chinese():
    kws = _extract_keywords("introducing retrieval-augmented generation improves GPT-4 accuracy by 86 points on FreshQA")
    # 应含方法名/实体（小写）
    assert any("retrieval" in k or "generation" in k for k in kws)
    assert any("gpt" in k.lower() for k in kws)
    assert len(kws) <= 8


def test_extract_keywords_chinese():
    kws = _extract_keywords("地球自转周期约 24 小时，太阳是恒星")
    # 应含中文块
    assert any("地球" in k or "自转" in k or "太阳" in k for k in kws)


def test_retrieve_with_meta_checked_dois_on_notfound():
    """DOI 查无（Crossref 404/空）→ checked_dois 记录该 DOI。"""
    c = [Claim(id="C001", original_snippet="DOI 10.9999/fake",
               normalized="DOI 10.9999/fake", type=ClaimType.METADATA)]
    # 模拟 Crossref 返回"查无但请求成功"（checked=True, found=False）
    with patch("retrieval.searcher.cr_doi_status") as m_cr, \
         patch("retrieval.searcher.oa_doi") as m_oa:
        m_cr.return_value = {"evidence": [], "checked": True, "checked_found": False}
        m_oa.return_value = []
        meta = retrieve_with_meta(c)
    assert "10.9999/fake" in meta["checked_dois"]


def test_retrieve_with_meta_no_checked_when_network_fail():
    """Crossref 网络失败（checked=False）→ 不加入 checked_dois（不能断言查无）。"""
    c = [Claim(id="C001", original_snippet="DOI 10.9999/x",
               normalized="DOI 10.9999/x", type=ClaimType.METADATA)]
    with patch("retrieval.searcher.cr_doi_status") as m_cr, \
         patch("retrieval.searcher.oa_doi") as m_oa:
        m_cr.return_value = {"evidence": [], "checked": False, "checked_found": False}
        m_oa.return_value = []
        meta = retrieve_with_meta(c)
    assert meta["checked_dois"] == set()


def test_retrieve_multi_source_for_numeric_claim():
    """非 DOI 主张应对 Crossref + OpenAlex(title) + OpenAlex(kw) 都查（mock 各源）。"""
    c = [Claim(id="C001", original_snippet="准确率提高 40%",
               normalized="准确率提高 40%", type=ClaimType.NUMERIC)]
    from core.models import Evidence
    from datetime import datetime, timezone
    fake_cr = [Evidence(id="E-cr", source_name="Crossref", url="http://cr", title="cr paper",
                        retrieved_at=datetime.now(timezone.utc))]
    fake_oa = [Evidence(id="E-oa", source_name="OpenAlex", url="http://oa", title="oa paper",
                        retrieved_at=datetime.now(timezone.utc))]
    with patch("retrieval.searcher.search_bibliographic") as m_cr, \
         patch("retrieval.searcher.search_by_title") as m_oa_title, \
         patch("retrieval.searcher.oa_doi") as m_oa_doi:
        m_cr.return_value = fake_cr
        m_oa_title.side_effect = [fake_oa, fake_oa]  # title 查 + kw 查
        m_oa_doi.return_value = []
        meta = retrieve_with_meta(c)
    ev_ids = {e.id for e in meta["evidence"]}
    # 两源证据都应在（去重后 cr + oa）
    assert "E-cr" in ev_ids
    assert "E-oa" in ev_ids
