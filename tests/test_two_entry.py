"""阶段 8 测试：两个检索入口（学术 + 其他/网页）+ 来源等级保守判定。

设计理由：
- web 检索器失败必须静默降级（不崩、不卡），与学术检索一致。
- 网页证据（tier=web）绝不能把主张升级到 VERIFIED——这是诚信底线。
- 快照向后兼容：老快照无 source_tier 字段时用默认 "academic"。
- 测试全部离线（mock HTTP），不依赖真实网络。
"""
import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from attribution.classifier import classify
from core.enums import ClaimStatus, ClaimType
from core.models import Claim, Evidence
from retrieval.searcher import retrieve_with_meta
from retrieval.snapshot import load_snapshot, save_snapshot
from retrieval.web_search import search_other, search_web, search_wikipedia


def _ev(tier="academic", snippet="", supports=None, doi=None, title="T", year=None):
    return Evidence(
        id="E-test",
        source_name={"academic": "Crossref", "wikipedia": "Wikipedia", "web": "Web"}[tier],
        url="https://x",
        title=title,
        year=year,
        doi=doi,
        retrieved_at=datetime.now(timezone.utc),
        snippet=snippet,
        supports=supports or [],
        source_tier=tier,
    )


# ---------- web 检索器：失败静默降级 ----------

def test_search_web_failure_returns_empty():
    """DDG 网络失败 → 空列表，不抛异常。"""
    import httpx
    with patch("retrieval.web_search.httpx.get", side_effect=httpx.ConnectError("timeout")):
        assert search_web("machine learning") == []


def test_search_wikipedia_failure_returns_empty():
    """Wikipedia 网络失败 → 空列表，不抛异常。"""
    import httpx
    with patch("retrieval.web_search.httpx.get", side_effect=httpx.ConnectError("timeout")):
        assert search_wikipedia("Earth") == []


def test_search_web_success_parses():
    """DDG 返回正常 HTML → 解析出 tier=web 证据。"""
    import httpx
    fake_html = (
        '<a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fpage">'
        "Example Page Title</a>"
        '<a class="result__snippet">Some snippet text here.</a>'
    )
    fake_resp = SimpleNamespace(status_code=200, text=fake_html)
    with patch("retrieval.web_search.httpx.get", return_value=fake_resp):
        evs = search_web("query")
    assert len(evs) == 1
    assert evs[0].source_tier == "web"
    assert evs[0].url == "https://example.com/page"  # 已解出真实 URL
    assert evs[0].snippet == "Some snippet text here."


def test_search_wikipedia_success_parses():
    """Wikipedia summary API 正常 → 解析出 tier=wikipedia 证据。"""
    import httpx
    fake_data = {
        "title": "Earth",
        "extract": "Earth is the third planet from the Sun.",
        "content_urls": {"desktop": {"page": "https://en.wikipedia.org/wiki/Earth"}},
    }
    fake_resp = SimpleNamespace(status_code=200, text="{}", json=lambda: fake_data)
    # 精确 title summary 命中（_wiki_search 也调 get，mock 需兼容）
    import httpx as _h
    with patch("retrieval.web_search.httpx.get", return_value=fake_resp):
        evs = search_wikipedia("Earth")
    assert len(evs) >= 1
    assert evs[0].source_tier == "wikipedia"
    assert "Earth" in evs[0].title
    assert "third planet" in (evs[0].snippet or "")


# ---------- 来源等级保守判定（诚信底线）----------

def test_web_tier_cannot_upgrade_to_verified():
    """普通网页证据 + 数字匹配 → 仍不是 VERIFIED（顶多 PARTIAL）。"""
    c = [Claim(id="C001", original_snippet="地球自转 24 小时", normalized="地球自转 24 小时",
               type=ClaimType.EXISTENCE)]
    web_ev = _ev(tier="web", snippet="the earth rotates in 24 hours", supports=["C001"])
    res = classify(c, [web_ev])
    assert res[0].status in (ClaimStatus.PARTIAL, ClaimStatus.INSUFFICIENT, ClaimStatus.UNVERIFIABLE)
    assert res[0].status != ClaimStatus.VERIFIED
    # 理由应体现"低质来源/仅供参考"
    assert "网页" in res[0].rationale or "参考" in res[0].rationale


def test_academic_tier_can_upgrade_to_verified():
    """学术证据 + 数字全匹配 → VERIFIED。"""
    c = [Claim(id="C001", original_snippet="精度提高 40%", normalized="精度提高 40%",
               type=ClaimType.NUMERIC)]
    acad = _ev(tier="academic", snippet="precision improved by 40%", supports=["C001"])
    res = classify(c, [acad])
    assert res[0].status == ClaimStatus.VERIFIED


def test_mixed_web_and_academic_no_all_academic():
    """网页证据命中数字、但无学术证据 → 不升级 VERIFIED。"""
    c = [Claim(id="C001", original_snippet="精度提高 40%", normalized="精度提高 40%",
               type=ClaimType.NUMERIC)]
    web_ev = _ev(tier="web", snippet="improved by 40%", supports=["C001"])
    res = classify(c, [web_ev])
    assert res[0].status != ClaimStatus.VERIFIED


# ---------- 两个检索入口路由 ----------

def test_retrieve_routes_web_for_existence_claim():
    """EXISTENCE 主张 → 学术 + 网页双入口合并（mock 各源）。"""
    c = [Claim(id="C001", original_snippet="地球是行星", normalized="地球是行星",
               type=ClaimType.EXISTENCE)]
    acad_ev = _ev(tier="academic", title="paper")
    web_ev = _ev(tier="web", title="webpage")
    with patch("retrieval.searcher.search_bibliographic") as m_cr, \
         patch("retrieval.searcher.search_by_title") as m_oa, \
         patch("retrieval.searcher.cr_doi_status") as m_doi, \
         patch("retrieval.searcher.oa_doi") as m_oa_doi, \
         patch("retrieval.searcher.web_search_other") as m_web:
        m_cr.return_value = [acad_ev]
        m_oa.return_value = []
        m_doi.return_value = {"evidence": [], "checked": False, "checked_found": False}
        m_oa_doi.return_value = []
        m_web.return_value = [web_ev]
        meta = retrieve_with_meta(c)
    # 调用过 web 入口
    assert m_web.called
    ev_ids = {e.id for e in meta["evidence"]}
    assert "E-test" in ev_ids  # 至少有一个证据


def test_metadata_doi_not_routed_to_web():
    """METADATA（含 DOI）→ 只走学术入口，不查网页。"""
    c = [Claim(id="C001", original_snippet="DOI 10.1/x", normalized="DOI 10.1/x",
               type=ClaimType.METADATA)]
    with patch("retrieval.searcher.cr_doi_status") as m_doi, \
         patch("retrieval.searcher.oa_doi") as m_oa_doi, \
         patch("retrieval.searcher.web_search_other") as m_web:
        m_doi.return_value = {"evidence": [_ev(doi="10.1/x", supports=["C001"])], "checked": True, "checked_found": True}
        m_oa_doi.return_value = []
        m_web.return_value = []
        retrieve_with_meta(c)
    # METADATA 不应调用 web 入口
    assert not m_web.called


# ---------- 快照向后兼容 ----------

def test_snapshot_without_tier_field_defaults_academic(tmp_path: Path):
    """老快照（无 source_tier 字段）加载后用默认 academic。"""
    p = tmp_path / "old.json"
    payload = {
        "saved_at": "2026-01-01T00:00:00Z",
        "count": 1,
        "evidence": [{
            "id": "E-1", "source_name": "Crossref", "url": "http://x",
            "title": "T", "authors": [], "year": 2020, "doi": "10.1/x",
            "retrieved_at": "2026-01-01T00:00:00+00:00", "snippet": "s",
            "supports": [], "support_level": "partial_support",
            # 无 source_tier 字段
        }],
    }
    p.write_text(json.dumps(payload), encoding="utf-8")
    loaded = load_snapshot(p)
    assert loaded[0].source_tier == "academic"  # 默认值


def test_snapshot_with_tier_field_roundtrip(tmp_path: Path):
    """新快照（带 source_tier）存读往返保留。"""
    p = tmp_path / "new.json"
    ev = _ev(tier="wikipedia", title="Earth", year=2024, supports=[])
    save_snapshot([ev], p)
    loaded = load_snapshot(p)
    assert loaded[0].source_tier == "wikipedia"
