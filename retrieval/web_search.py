"""非学术证据检索器：Wikipedia + DuckDuckGo HTML 双源（免 key，可离线降级）。

设计理由（阶段 8：两个检索入口）：
- 学术入口：Crossref / OpenAlex（文献）。
- 其他入口（本模块）：Wikipedia（权威非学术，常识/机构/人物）+ DuckDuckGo HTML（通用网页兜底）。
- 来源等级（source_tier）：
    wikipedia → "wikipedia"（较强非学术来源）
    duckduckgo 网页 → "web"（普通网页，低质，仅供参考）
- 失败/限流/无结果 → 该源返回空，不影响其他源，不崩、不卡（与学术检索一致的静默降级）。
- 明确：网页证据 ≠ 学术证据。分类器对 web tier 保守处理（详见 classifier.py）。
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Dict, List, Optional

import httpx

from core.models import Evidence

_TIMEOUT = 12.0
_WIKI_BASE = "https://en.wikipedia.org"
_DDG_BASE = "https://html.duckduckgo.com/html/"
_UA = "Mozilla/5.0 (compatible; VeriMindAI/1.0; +https://github.com)"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def search_wikipedia(query: str, limit: int = 3) -> List[Evidence]:
    """Wikipedia 摘要 API（免 key）。返回 tier='wikipedia' 的证据。

    查询：GET /api/rest_v1/page/summary/{title} 或 search API。
    失败/无结果 → 空列表（不抛异常）。
    """
    q = (query or "").strip()
    if not q:
        return []
    out: List[Evidence] = []
    # 1) 先试精确 title summary（命中率高、质量高）
    out.extend(_wiki_summary_by_title(q, limit=1))
    # 2) 再试 search API（模糊召回）
    if len(out) < limit:
        out.extend(_wiki_search(q, limit - len(out)))
    return out[:limit]


def _wiki_summary_by_title(title: str, limit: int) -> List[Evidence]:
    url = f"{_WIKI_BASE}/api/rest_v1/page/summary/{title}"
    try:
        resp = httpx.get(
            url,
            params={"format": "json"} if False else {},
            headers={"User-Agent": _UA, "Accept": "application/json"},
            timeout=_TIMEOUT,
        )
        if resp.status_code != 200:
            return []
        data = resp.json()
        return [_wiki_make_evidence(data, title)]
    except (httpx.HTTPError, ValueError, KeyError):
        return []


def _wiki_search(query: str, limit: int) -> List[Evidence]:
    url = f"{_WIKI_BASE}/w/api.php"
    params = {
        "action": "query",
        "list": "search",
        "srsearch": query,
        "srlimit": limit,
        "srprop": "snippet",
        "format": "json",
        "srnamespace": "0",
    }
    try:
        resp = httpx.get(url, params=params, headers={"User-Agent": _UA}, timeout=_TIMEOUT)
        if resp.status_code != 200:
            return []
        results = resp.json().get("query", {}).get("search", [])
        out: List[Evidence] = []
        for r in results:
            page_title = r.get("title", "")
            if not page_title:
                continue
            # 用 summary API 拿更干净的片段
            detail = _wiki_summary_by_title(page_title, limit=1)
            if detail:
                snippet = detail[0].snippet or r.get("snippet", "")
                detail[0].snippet = snippet
                out.append(detail[0])
            else:
                out.append(
                    Evidence(
                        id=f"E-wiki-{page_title[:16].lower().replace(' ', '_')}",
                        source_name="Wikipedia",
                        url=f"{_WIKI_BASE}/wiki/{page_title.replace(' ', '_')}",
                        title=page_title,
                        retrieved_at=_now(),
                        snippet=_strip_html(r.get("snippet", ""))[:300] or None,
                        source_tier="wikipedia",
                    )
                )
        return out
    except (httpx.HTTPError, ValueError, KeyError):
        return []


def _wiki_make_evidence(data: Dict, requested_title: str) -> Optional[Evidence]:
    title = data.get("title") or requested_title
    if not title:
        return None
    extract = (data.get("extract") or "").strip()
    url = data.get("content_urls", {}).get("desktop", {}).get("page", f"{_WIKI_BASE}/wiki/{title}")
    year_raw = data.get("published_time")
    year = year_raw.get("year") if isinstance(year_raw, dict) else None
    return Evidence(
        id=f"E-wiki-{title[:16].lower().replace(' ', '_')}",
        source_name="Wikipedia",
        url=url,
        title=title,
        year=year,
        retrieved_at=_now(),
        snippet=extract[:500] or None,
        source_tier="wikipedia",
    )


def _strip_html(s: str) -> str:
    return re.sub(r"<[^>]+>", "", s or "").strip()


def search_web(query: str, limit: int = 3) -> List[Evidence]:
    """DuckDuckGo HTML 接口（免 key、免注册）。返回 tier='web' 的证据。

    失败/限流/无结果 → 空列表（不抛异常）。
    注意：DDG 结果无可靠 year / doi / 作者，只有 snippet 与 url，
    因此只能作"低质网页参考"，供分类器保守使用。
    """
    q = (query or "").strip()
    if not q:
        return []
    url = f"{_DDG_BASE}?"
    out: List[Evidence] = []
    try:
        resp = httpx.get(
            f"{_DDG_BASE}",
            params={"q": q},
            headers={"User-Agent": _UA},
            timeout=_TIMEOUT,
            follow_redirects=True,
        )
        if resp.status_code != 200:
            return []
        html = resp.text
        # 解析 DDG HTML：结果在 <a class="result__a" href="...">标题</a>
        # snippet 在 <a class="result__snippet">...
        links = re.findall(r'<a[^>]*class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', html, re.S)
        snippets = re.findall(r'<a[^>]*class="result__snippet"[^>]*>(.*?)</a>', html, re.S)
        for i, (raw_url, raw_title) in enumerate(links[:limit]):
            # DDG 的 href 常是重定向包装（//duckduckgo.com/l/?uddg=...），解出真实 URL
            real_url = _unwrap_ddg_url(raw_url)
            title = _strip_html(raw_title)[:120]
            snip = _strip_html(snippets[i])[:300] if i < len(snippets) else ""
            out.append(
                Evidence(
                    id=f"E-web-{i + 1}",
                    source_name="Web",
                    url=real_url or raw_url,
                    title=title,
                    retrieved_at=_now(),
                    snippet=snip or None,
                    source_tier="web",
                )
            )
        return out
    except (httpx.HTTPError, ValueError):
        return []


def _unwrap_ddg_url(href: str) -> str:
    """DuckDuckGo 结果常包在 //duckduckgo.com/l/?uddg=<urlencoded> 里，解出真实 URL。"""
    import urllib.parse
    href = (href or "").strip()
    if "uddg=" in href:
        try:
            q = urllib.parse.parse_qs(href.split("?", 1)[1])
            if "uddg" in q:
                return q["uddg"][0]
        except Exception:  # noqa: BLE001
            pass
    if href.startswith("//"):
        return "https:" + href
    return href


def search_other(query: str, limit: int = 3) -> List[Evidence]:
    """非学术入口统一出口：Wikipedia + 网页双源合并（各自独立失败互不影响）。"""
    evs = search_wikipedia(query, limit=limit) + search_web(query, limit=limit)
    # 按 url 去重
    seen: set = set()
    out: List[Evidence] = []
    for e in evs:
        if e.url and e.url not in seen:
            seen.add(e.url)
            out.append(e)
    return out
