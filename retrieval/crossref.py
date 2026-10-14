"""Crossref 检索器：DOI 精确查询 + 书目模糊查询。

设计理由：
- Crossref 是文献元数据的事实标准，DOI 精确查询最可靠。
- 免费、无 key，但建议提供 mailto 以遵守其使用条款（Polite Pool）。
- 失败/查无结果返回空列表 + 记录原因，绝不伪造文献。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx

from core.models import Evidence

_BASE = "https://api.crossref.org"
_TIMEOUT = 20.0


def _make_evidence(item: Dict[str, Any], source_name: str = "Crossref") -> Optional[Evidence]:
    """把 Crossref item 转成 Evidence；缺关键字段时返回 None。"""
    doi = item.get("DOI", "")
    if not doi:
        return None
    title_list = item.get("title", [])
    title = title_list[0] if title_list else ""
    authors = [
        f"{a.get('family', '')} {a.get('given', '')}".strip()
        for a in item.get("author", [])
        if a
    ]
    year: Optional[int] = None
    pub = item.get("published", {}).get("date-parts", [[None]])
    if pub and pub[0] and pub[0][0]:
        year = pub[0][0]

    url = f"https://doi.org/{doi}"
    abstract = item.get("abstract", "")
    # Crossref 摘要常为 JATS XML，这里简单去标签
    if abstract:
        import re
        abstract = re.sub(r"<[^>]+>", "", abstract)[:500]

    return Evidence(
        id=f"E-{doi[-12:]}",
        source_name=source_name,
        url=url,
        title=title,
        authors=authors,
        year=year,
        doi=doi,
        retrieved_at=datetime.now(timezone.utc),
        snippet=abstract or None,
    )


def search_by_doi(doi: str, mailto: str = "") -> List[Evidence]:
    """按 DOI 精确查询。查无结果/网络失败 → 空列表。"""
    return search_by_doi_with_status(doi, mailto=mailto)["evidence"]


def search_by_doi_with_status(doi: str, mailto: str = "") -> dict:
    """按 DOI 精确查询，回传 checked（请求确实成功、能判断存不存在）。

    返回 {"evidence": List[Evidence], "checked": bool, "checked_found": bool}
      checked=True 仅当请求成功到达 Crossref（无论查到与否）。
      网络失败 checked=False → 上层不能据此断言"引用不存在"。
    """
    doi = (doi or "").strip()
    if not doi:
        return {"evidence": [], "checked": False, "checked_found": False}
    url = f"{_BASE}/works/{doi}"
    params: Dict[str, str] = {"mailto": mailto} if mailto else {}
    try:
        resp = httpx.get(url, params=params, timeout=_TIMEOUT)
        if resp.status_code != 200:
            # 404 = Crossref 明确查无（checked=True，found=False）；其他状态 = 不确定
            checked = resp.status_code == 404
            return {"evidence": [], "checked": checked, "checked_found": False}
        item = resp.json().get("message", {})
        ev = _make_evidence(item, "Crossref")
        return {"evidence": [ev] if ev else [], "checked": True, "checked_found": bool(ev)}
    except httpx.HTTPError:
        return {"evidence": [], "checked": False, "checked_found": False}


def search_bibliographic(query: str, mailto: str = "", limit: int = 5) -> List[Evidence]:
    """按标题/作者/关键词模糊查询，返回前 N 条。"""
    query = (query or "").strip()
    if not query:
        return []
    url = f"{_BASE}/works"
    params: Dict[str, Any] = {"query.bibliographic": query, "rows": limit}
    if mailto:
        params["mailto"] = mailto
    try:
        resp = httpx.get(url, params=params, timeout=_TIMEOUT)
        if resp.status_code != 200:
            return []
        items = resp.json().get("message", {}).get("items", [])
        result: List[Evidence] = []
        for it in items:
            ev = _make_evidence(it, "Crossref")
            if ev:
                result.append(ev)
        return result
    except httpx.HTTPError:
        return []
