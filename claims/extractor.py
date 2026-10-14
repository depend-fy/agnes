"""事实主张提取器（规则桩版）。

设计理由：
- 阶段 2 不调用 LLM，用正则 + 关键词把文本拆成原子主张，保证闭环可离线跑通。
- 接口签名稳定为 `extract(text) -> List[Claim]`，阶段 3 直接替换实现为 LLM 调用即可。
- 规则能识别的常见模式：DOI、年份、数值、因果结论、存在性。

  识别不到的文本仍会产出一条 GENERAL 主张，避免空列表。
"""
from __future__ import annotations

import re
from typing import List

from core.enums import ClaimStatus, ClaimType
from core.models import Claim

_DOI_RE = re.compile(r"\bDOI\b\s*(?:为|是|[:：]|of)?\s*([0-9]{1,3}\.[^\s,;，。]+)", re.IGNORECASE)
_YEAR_RE = re.compile(r"(?:published\s*in|published|发表|出现)\s*(?:于|於|in)?\s*([0-9]{4})\s*年?", re.IGNORECASE)
_NUMERIC_RE = re.compile(
    r"(?:improve[d]?|提升|提高|降低|减少|下降|increase[d]?|decrease[d]?)\s*(?:by)?\s*([0-9]+(?:\.[0-9]+)?)\s*[%]?",
    re.IGNORECASE,
)
_CAUSAL_RE = re.compile(
    r"(?:prove[d]?|demonstrate[s]?|show[s]?|证明|表明|说明)\s*(.{5,80}?)(?:[.。;；]|$)",
    re.IGNORECASE | re.DOTALL,
)
_EXISTENCE_RE = re.compile(r"\b(?:a|an|the)\s+(?:study|paper|research)\b|一项研究|一篇论文|一项论文", re.IGNORECASE)


def _snippet_for_match(text: str, m: re.Match) -> str:
    start = max(0, m.start() - 30)
    end = min(len(text), m.end() + 30)
    return text[start:end].strip()


def _infer_type(kind: str) -> ClaimType:
    if kind == "doi":
        return ClaimType.METADATA
    if kind == "year":
        return ClaimType.METADATA
    if kind == "numeric":
        return ClaimType.NUMERIC
    if kind == "causal":
        return ClaimType.CAUSAL
    if kind == "existence":
        return ClaimType.EXISTENCE
    return ClaimType.GENERAL


def _infer_priority(kind: str) -> int:
    return {
        "doi": 1,
        "year": 2,
        "numeric": 2,
        "causal": 3,
        "existence": 4,
        "general": 5,
    }.get(kind, 5)


def extract(text: str) -> List[Claim]:
    """把输入文本拆成原子主张列表。

    输出：每个匹配到的模式生成一条 Claim，按出现顺序编号 C001, C002, ...
    无匹配时至少返回一条 GENERAL 主张（原文整段），避免空列表。
    """
    text = (text or "").strip()
    if not text:
        return []

    claims: List[Claim] = []

    def add(kind: str, snippet: str, normalized: str) -> None:
        claims.append(
            Claim(
                id=f"C{len(claims) + 1:03d}",
                original_snippet=snippet,
                normalized=normalized,
                type=_infer_type(kind),
                priority=_infer_priority(kind),
                status=ClaimStatus.UNVERIFIED,
            )
        )

    for m in _DOI_RE.finditer(text):
        add("doi", _snippet_for_match(text, m), f"文献 DOI 为 {m.group(1)}")

    for m in _YEAR_RE.finditer(text):
        add("year", _snippet_for_match(text, m), f"相关研究发表于 {m.group(1)} 年")

    for m in _NUMERIC_RE.finditer(text):
        add("numeric", _snippet_for_match(text, m), f"数值提升幅度为 {m.group(1)}%")

    m = _CAUSAL_RE.search(text)
    if m and len(claims) < 8:
        snippet = m.group(0)
        add("causal", snippet, f"研究结论：{snippet[:80]}")

    m2 = _EXISTENCE_RE.search(text)
    if m2 and len(claims) < 10:
        add("existence", _snippet_for_match(text, m2), "存在相关研究/论文")

    if not claims:
        add("general", text[:200], f"原文陈述：{text[:80]}")

    return claims
