"""统一检索入口：按主张类型路由到检索源（修复版，多源并发 + 关键词抽取）。

修复方向（用户选择 A）：
- 含 DOI 的主张 → Crossref 精确查（最可靠）；查无则记录到 checked_dois。
- 非 DOI 主张 → **关键词抽取**后，对 Crossref(bibliographic) + OpenAlex(title) +
  OpenAlex(keywords) **都查**，合并去重，提高召回。
- 网络失败 / 查无结果 → 该源返回空，不影响其他源；由分类器标记 UNVERIFIABLE。
- 单条主张最多产出 top-K 证据，避免证据爆炸。

回传 checked_dois：
- `retrieve(claims)` 仍返回 List[Evidence]（向后兼容）。
- `retrieve_with_meta(claims)` 返回 {"evidence": [...], "checked_dois": set}，
  供 pipeline 传给 classifier，让"引用不存在"只在 DOI 被精确查证且查无时才给。
"""
from __future__ import annotations

import re
from typing import List, Set

from core.enums import ClaimType
from core.models import Claim, Evidence
from core.config import get_settings
from retrieval.crossref import search_bibliographic, search_by_doi_with_status as cr_doi_status
from retrieval.openalex import search_by_doi as oa_doi, search_by_title
from retrieval.web_search import search_other as web_search_other

_DOI_RE = re.compile(r"\b([0-9]{1,3}\.[0-9]{0,12}/[^\s,;，。]+)\b")
_TOP_K = 5

# 哪些主张类型走"其他"入口（非学术：常识/机构/人物/存在性/通用）。
# METADATA（含 DOI）只走学术入口，保证引用核验仍用文献源。
_WEB_TYPES = {
    ClaimType.EXISTENCE,
    ClaimType.TIME_PERSON_ORG,
    ClaimType.GENERAL,
    ClaimType.CAUSAL,
    ClaimType.NUMERIC,
    ClaimType.LOGIC,
}


def _web_enabled(settings) -> bool:
    """是否启用非学术（网页）检索。默认开启；可通过 env 关闭。"""
    return getattr(settings, "enable_web_search", True)

# 简单停用词（中英），抽关键词时剔除
_STOPWORDS = {
    "的", "了", "在", "是", "和", "与", "或", "及", "把", "被", "将", "可以", "能够",
    "方法", "研究", "论文", "表明", "显示", "提出", "一种", "基于", "利用", "采用",
    "the", "a", "an", "and", "or", "of", "in", "on", "to", "for", "is", "are",
    "was", "were", "this", "that", "with", "using", "based", "shows", "show",
    "proposes", "propose", "method", "methods", "study", "paper", "result", "results",
}


def _extract_doi(claim: Claim) -> str:
    """从主张里提取 DOI（若为 METADATA 类型）。"""
    m = _DOI_RE.search(claim.original_snippet or "")
    if m:
        return m.group(1)
    m2 = _DOI_RE.search(claim.normalized or "")
    return m2.group(1) if m2 else ""


def _extract_keywords(text: str) -> List[str]:
    """从主张抽候选关键词（中英混排，去停用词与纯数字/标点）。

    策略：
    - 英文：连续字母 3~30 字符，小写化。
    - 中文：无分词库，取 2~6 字片段（按标点/空格切块后取有信息量的块）。
    - 剔除停用词与纯数字；去重；返回最多 8 个。
    """
    text = (text or "").strip()
    if not text:
        return []
    kws: List[str] = []
    # 英文词
    for w in re.findall(r"[A-Za-z][A-Za-z\-]{2,29}", text):
        lw = w.lower()
        if lw not in _STOPWORDS and lw not in kws:
            kws.append(lw)
    # 中文块：按标点/空格切，保留 2~6 字且含 CJK 的块
    for chunk in re.split(r"[\s,，.。;；:：!！?？()（）\[\]【】]+", text):
        cjk = re.findall(r"[\u4e00-\u9fa5]{2,6}", chunk)
        for c in cjk:
            if c not in _STOPWORDS and c not in kws:
                kws.append(c)
    return kws[:8]


def _dedupe(evs: List[Evidence], out: List[Evidence], seen: Set[str]) -> None:
    for ev in evs:
        key = ev.doi or ev.title.lower()
        if key and key not in seen:
            seen.add(key)
            out.append(ev)


def retrieve_with_meta(claims: List[Claim]) -> dict:
    """检索 + 回传 checked_dois。返回 {"evidence": [...], "checked_dois": set}。"""
    settings = get_settings()
    mailto = settings.crossref_mailto
    out: List[Evidence] = []
    seen: Set[str] = set()
    checked_dois: Set[str] = set()

    for c in claims:
        ev_list: List[Evidence] = []
        if c.type == ClaimType.METADATA:
            doi = _extract_doi(c)
            if doi:
                cr = cr_doi_status(doi, mailto=mailto)
                found = cr["evidence"]
                if not found:
                    oa = oa_doi(doi, mailto=mailto)
                    found = oa
                    # OpenAlex 也查无：只有 Crossref 请求成功（非网络失败）时
                    # 才认为“确实查过且不存在”，加入 checked_dois
                    if not found and cr.get("checked"):
                        checked_dois.add(doi.lower())
                ev_list = found
            else:
                # METADATA 但无 DOI → 用 bibliographic 查
                ev_list = search_bibliographic(c.normalized, mailto=mailto, limit=_TOP_K)
        else:
            # 非 DOI 主张：学术入口（Crossref bibliographic + OpenAlex title + keywords）
            kws = _extract_keywords(c.normalized)
            kw_join = " ".join(kws) if kws else c.normalized
            cr = search_bibliographic(kw_join, mailto=mailto, limit=_TOP_K)
            oa_title = search_by_title(c.normalized, mailto=mailto, limit=_TOP_K)
            oa_kw = search_by_title(kw_join, mailto=mailto, limit=_TOP_K) if kw_join else []
            ev_list = cr + oa_title + oa_kw
            # 阶段 8：非学术类型补"其他"入口（Wikipedia + 网页），学术证据为主、网页为辅
            if c.type in _WEB_TYPES and _web_enabled(settings):
                ev_list = ev_list + web_search_other(c.normalized, limit=_TOP_K)

        _dedupe(ev_list, out, seen)
        # 标记证据支持哪些主张（去重后追加）
        for ev in out:
            if c.id not in ev.supports:
                ev.supports.append(c.id)

    return {"evidence": out, "checked_dois": checked_dois}


def retrieve(claims: List[Claim]) -> List[Evidence]:
    """向后兼容：只返回证据列表。"""
    return retrieve_with_meta(claims)["evidence"]
