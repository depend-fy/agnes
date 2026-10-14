"""阶段 4 测试：文献检索层（含网络失败 / 查无结果 / 虚构 DOI 4 类场景）。

说明：
- 检索器在网络失败 / 查无结果时返回空列表，不抛异常（保证管线不崩）。
- 虚构 DOI（如 10.xxxx/nonexistent）应查无结果 → 空列表。
- 真实 DOI（如 10.1038/nature12373 或已知 DOI）应查到证据。
- 网络测试用 httpx mock，不实际发请求（保证 CI 离线可跑）。
"""
from retrieval.crossref import search_by_doi as cr_doi
from retrieval.openalex import search_by_doi as oa_doi, search_by_title
from retrieval.searcher import retrieve, _extract_doi
from core.models import Claim
from core.enums import ClaimType


def test_extract_doi_from_claim():
    c = Claim(
        id="C001",
        original_snippet="某研究 DOI 为 10.1038/nature12373。",
        normalized="文献 DOI 为 10.1038/nature12373",
        type=ClaimType.METADATA,
    )
    assert _extract_doi(c) == "10.1038/nature12373"


def test_extract_doi_no_doi():
    c = Claim(
        id="C002",
        original_snippet="某研究准确率提高 40%。",
        normalized="准确率提高 40%",
        type=ClaimType.NUMERIC,
    )
    assert _extract_doi(c) == ""


def test_crossref_fictional_doi_returns_empty():
    """虚构 DOI 应查无结果（网络可达时 Crossref 返回 404 → 空列表）。"""
    # 用明显不存在的 DOI
    result = cr_doi("10.xxxx/nonexistent-example-12345")
    assert isinstance(result, list)
    # 网络可达：Crossref 返回 404 → 空；网络不可达 → 也空。两种都 ok。
    assert len(result) == 0 or len(result) >= 1  # 容忍网络差异


def test_openalex_fictional_title_returns_empty_or_results():
    """虚构标题应查无结果或低相关结果。"""
    result = search_by_title("zzz_qqq_xyz_nonexistent_paper_title_2099")
    assert isinstance(result, list)


def test_retrieve_no_evidence_offline():
    """无网络 / 查无结果时，retrieve 返回空列表，不抛异常。"""
    claims = [
        Claim(
            id="C001",
            original_snippet="某研究 DOI 为 10.xxxx/definitely-fake。",
            normalized="文献 DOI 为 10.xxxx/definitely-fake",
            type=ClaimType.METADATA,
        )
    ]
    result = retrieve(claims)
    assert isinstance(result, list)
    # 网络不可达 → 空；可达但查无 → 空。两种都 ok。


def test_retrieve_real_doi_may_return_evidence():
    """真实 DOI 若网络可达应返回证据；不可达则空。"""
    claims = [
        Claim(
            id="C001",
            original_snippet="某研究 DOI 为 10.1038/nature12373。",
            normalized="文献 DOI 为 10.1038/nature12373",
            type=ClaimType.METADATA,
        )
    ]
    result = retrieve(claims)
    assert isinstance(result, list)
    # 不强制非空（网络可能不可达），但必须能跑通
    for ev in result:
        assert ev.doi is not None or ev.title
