"""OpenAlex 检索器：标题 / 关键词 / DOI 查询（免费、含摘要）。

设计理由：
- OpenAlex 对标题模糊匹配效果好，且有 abstract（inverted index 需重组）。
- 免费无 key；摘要重组后仅作为"摘要层面"证据，不声称读了全文。
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx

from core.models import Evidence

_BASE = "https://api.openalex.org"
_TIMEOUT = 20.0


def _rebuild_abstract(inv: Optional[Dict[str, Any]]) -> str:
    """OpenAlex 摘要以 inverted index 存储，需重组为可读文本。"""
    if not inv:
        return ""
    pos: Dict[int, str] = {}
    for word, idxs in inv.items():
        for i in idxs:
            pos[i] = word
    if not pos:
        return ""
    return " ".join(pos[i] for i in sorted(pos))[:500]


def _make_evidence(item: Dict[str, Any]) -> Optional[Evidence]:
    doi = item.get("doi", "")
    if doi:
        doi = doi.replace("https://doi.org/", "").strip()
    title = item.get("title") or item.get("display_name") or ""
    authors = [
        (a.get("author") or {}).get("display_name", "")
        for a in item.get("authorships", [])
    ]
    authors = [a for a in authors if a]
    year: Optional[int] = None
    pub_date = item.get("publication_date", "")
    if pub_date:
        year = int(pub_date[:4])
    url = item.get("landing_page_url") or item.get("id", "")
    abstract = _rebuild_abstract(item.get("abstract_inverted_index"))

    return Evidence(
        id=f"E-{item.get('id', title[:16])[-12:]}",
        source_name="OpenAlex",
        url=url or (f"https://doi.org/{doi}" if doi else ""),
        title=title,
        authors=authors,
        year=year,
        doi=doi or None,
        retrieved_at=datetime.now(timezone.utc),
        snippet=abstract or None,
    )


def search_by_title(title: str, mailto: str = "", limit: int = 5) -> List[Evidence]:
    """按标题模糊查询。"""
    title = (title or "").strip()
    if not title:
        return []
    url = f"{_BASE}/works"
    params: Dict[str, Any] = {"search": title, "per-page": limit, "sort": "relevance_score:desc"}
    if mailto:
        params["mailto"] = mailto
    try:
        resp = httpx.get(url, params=params, timeout=_TIMEOUT)
        if resp.status_code != 200:
            return []
        items = resp.json().get("results", [])
        result: List[Evidence] = []
        for it in items:
            ev = _make_evidence(it)
            if ev:
                result.append(ev)
        return result
    except httpx.HTTPError:
        return []


def search_by_doi(doi: str, mailto: str = "") -> List[Evidence]:
    """按 DOI 精确查询 OpenAlex。"""
    doi = (doi or "").strip()
    if not doi:
        return []
    url = f"{_BASE}/works"
    params: Dict[str, str] = {"filter": f"doi:https://doi.org/{doi}", "per-page": 1}
    if mailto:
        params["mailto"] = mailto
    try:
        resp = httpx.get(url, params=params, timeout=_TIMEOUT)
        if resp.status_code != 200:
            return []
        items = resp.json().get("results", [])
        result = [_make_evidence(it) for it in items]
        return [e for e in result if e]
    except httpx.HTTPError:
        return []


def search_by_keywords(keywords: str, mailto: str = "", limit: int = 5) -> List[Evidence]:
    """按关键词查询（与 search_by_title 同接口，语义不同）。"""
    return search_by_title(keywords, mailto=mailto, limit=limit)
