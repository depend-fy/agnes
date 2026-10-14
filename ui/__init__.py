"""UI 视图逻辑（纯函数，与 Streamlit 解耦，可测试）。

设计理由：
- Streamlit 渲染器只做"调用 + 摆位"，所有"计算展示数据"的逻辑放这里，
  保证可单测、可复用（导出报告也用它）。
- 颜色语义统一在此定义，避免渲染层各自硬编码导致红绿用错。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from core.enums import ClaimStatus
from core.models import Claim, DetectionReport, VerificationResult

# ===== 统一颜色语义（阶段 7/8 界面优化核心）=====
# 绿=有充分证据 / 黄=表述过度或证据有限 / 红=无法证实或疑似错误 / 灰=尚未检索到足够资料
COLOR_GREEN = "#1a7f37"
COLOR_YELLOW = "#9a6700"
COLOR_RED = "#cf222e"
COLOR_GRAY = "#6e7781"
COLOR_BG_GREEN = "#dafbe0"
COLOR_BG_YELLOW = "#fff8c5"
COLOR_BG_RED = "#ffebe9"
COLOR_BG_GRAY = "#eaeef2"


def status_color(status: ClaimStatus) -> str:
    """状态 → 文字颜色。绿/黄/红/灰四色语义，红绿不用于无关装饰。"""
    return {
        ClaimStatus.VERIFIED: COLOR_GREEN,
        ClaimStatus.PARTIAL: COLOR_YELLOW,
        ClaimStatus.CONTRADICTED: COLOR_RED,
        ClaimStatus.CONFLICTING_SOURCES: COLOR_RED,
        ClaimStatus.INSUFFICIENT: COLOR_YELLOW,
        ClaimStatus.UNVERIFIABLE: COLOR_GRAY,
        ClaimStatus.UNVERIFIED: COLOR_GRAY,
    }.get(status, COLOR_GRAY)


def status_bg_color(status: ClaimStatus) -> str:
    """状态 → 背景色（配合文字色）。"""
    return {
        ClaimStatus.VERIFIED: COLOR_BG_GREEN,
        ClaimStatus.PARTIAL: COLOR_BG_YELLOW,
        ClaimStatus.CONTRADICTED: COLOR_BG_RED,
        ClaimStatus.CONFLICTING_SOURCES: COLOR_BG_RED,
        ClaimStatus.INSUFFICIENT: COLOR_BG_YELLOW,
        ClaimStatus.UNVERIFIABLE: COLOR_BG_GRAY,
        ClaimStatus.UNVERIFIED: COLOR_BG_GRAY,
    }.get(status, COLOR_BG_GRAY)


def status_label_zh(status: ClaimStatus) -> str:
    """状态 → 中文标签。"""
    return {
        ClaimStatus.VERIFIED: "已核实",
        ClaimStatus.CONTRADICTED: "存在矛盾",
        ClaimStatus.PARTIAL: "部分支持",
        ClaimStatus.INSUFFICIENT: "证据不足",
        ClaimStatus.UNVERIFIABLE: "暂无法核验",
        ClaimStatus.UNVERIFIED: "未核验",
        ClaimStatus.CONFLICTING_SOURCES: "来源冲突",
    }.get(status, status.value)


# ===== 整体可信度评分（0-100，快速判断用）=====
# 计分规则（透明、可解释，不编造概率）：
#   VERIFIED=+30  PARTIAL=+15  INSUFFICIENT=+0  UNVERIFIABLE=+0
#   CONTRADICTED=-30  CONFLICTING_SOURCES=-15  UNVERIFIED=+0
# 总分 / 主张数 归一化到 0-100；含负分再 clip 到 0。
_STATUS_SCORE = {
    ClaimStatus.VERIFIED: 30,
    ClaimStatus.PARTIAL: 15,
    ClaimStatus.INSUFFICIENT: 0,
    ClaimStatus.UNVERIFIABLE: 0,
    ClaimStatus.UNVERIFIED: 0,
    ClaimStatus.CONTRADICTED: -30,
    ClaimStatus.CONFLICTING_SOURCES: -15,
}


def overall_confidence(verification: List[VerificationResult]) -> Dict[str, Any]:
    """计算整体可信度（0-100）+ 定性档位。

    返回 {score, band, band_color, band_label, breakdown}。
    band ∈ high/medium/low，对应绿/黄/红/灰。
    说明：这是"基于当前证据的核验覆盖度"，不是"文本为真概率"，不展示伪精确概率。
    """
    if not verification:
        return {
            "score": 0, "band": "none", "band_color": COLOR_GRAY,
            "band_label": "无可核验主张", "breakdown": {},
        }
    total = sum(_STATUS_SCORE.get(v.status, 0) for v in verification)
    # 归一化：满分 = 30 × 主张数
    max_total = 30 * len(verification)
    raw = total / max_total if max_total else 0.0
    score = int(max(0, min(1.0, raw + 0.5)) * 100)  # 加入 0.5 偏移让"无矛盾无证据"也有基础分
    # 有矛盾/冲突直接压低档位
    has_contra = any(v.status in (ClaimStatus.CONTRADICTED, ClaimStatus.CONFLICTING_SOURCES) for v in verification)
    breakdown: Dict[str, int] = {}
    for v in verification:
        breakdown[v.status.value] = breakdown.get(v.status.value, 0) + 1
    if has_contra:
        band = "low"
        band_color = COLOR_RED
        band_label = "存在矛盾/来源冲突"
    elif score >= 70:
        band = "high"
        band_color = COLOR_GREEN
        band_label = "证据充分"
    elif score >= 40:
        band = "medium"
        band_color = COLOR_YELLOW
        band_label = "表述过度或证据有限"
    else:
        band = "low"
        band_color = COLOR_GRAY if not has_contra else COLOR_RED
        band_label = "证据有限，待核实"
    return {
        "score": score, "band": band, "band_color": band_color,
        "band_label": band_label, "breakdown": breakdown,
    }


# ===== 多模型共识程度 =====
# 按主张聚合各角色判断，看是否一致。
# 简化：同一主张下多角色 judgement 若都指向"有问题"或都指向"可接受"→ 高度一致；
# 指向不同 → 存在分歧；证据不足 → 证据不足。
def consensus_level(ver: VerificationResult) -> Dict[str, Any]:
    """单条主张的共识程度。

    返回 {level, color, label, divergent_roles, note}
    level ∈ high/low/insufficient。
    """
    js = ver.role_judgements
    if not js:
        return {"level": "insufficient", "color": COLOR_GRAY,
                "label": "暂无多角色判断", "divergent_roles": [], "note": "无角色判断记录"}
    # 用状态作为"共识锚点"：状态本身已综合证据；角色判断用于看分歧
    status_problematic = ver.status in (ClaimStatus.CONTRADICTED, ClaimStatus.CONFLICTING_SOURCES,
                                       ClaimStatus.INSUFFICIENT)
    # 粗略分歧检测：角色判断文本里是否出现"证据不足/无法判定"等 vs "成立/支持"
    neg_kw = ("证据不足", "无法判定", "暂无法", "不成立", "矛盾", "无证据")
    pos_kw = ("成立", "支持", "一致", "可核实", "正确")
    neg_roles = [j.role.value for j in js if any(k in j.judgement for k in neg_kw)]
    pos_roles = [j.role.value for j in js if any(k in j.judgement for k in pos_kw)]
    if neg_roles and pos_roles:
        return {"level": "low", "color": COLOR_RED, "label": "存在分歧",
                "divergent_roles": sorted(set(neg_roles) | set(pos_roles)),
                "note": f"以下角色意见不一致：{', '.join(sorted(set(neg_roles + pos_roles)))}"}
    if any("证据不足" in j.judgement or "无法判定" in j.judgement or "暂无法" in j.judgement for j in js):
        return {"level": "insufficient", "color": COLOR_GRAY, "label": "证据不足",
                "divergent_roles": [], "note": "多角色均认为证据不足以判定"}
    return {"level": "high", "color": COLOR_GREEN, "label": "高度一致",
            "divergent_roles": [], "note": "多角色判断方向一致"}


# ===== 证据链（论断 → 关键词 → 检索论文 → 原文依据 → 多模型结论）=====
def evidence_chain(
    claim: Claim,
    ver: VerificationResult,
    evidence: List,
) -> List[Dict[str, Any]]:
    """生成该主张的证据链路，供可视化。"""
    ev_by_id = {e.id: e for e in evidence}
    related = [ev_by_id[eid] for eid in ver.evidence_ids if eid in ev_by_id]
    chain: List[Dict[str, Any]] = [
        {"step": "论断", "text": claim.normalized},
        {"step": "关键词", "text": _claim_keywords(claim.normalized)},
    ]
    for ev in related:
        chain.append({
            "step": "检索论文",
            "text": ev.title,
            "url": ev.url,
            "source": ev.source_name,
            "year": ev.year,
            "doi": ev.doi,
        })
        chain.append({"step": "原文依据", "text": ev.snippet or "（摘要未提供片段）"})
    chain.append({
        "step": "多模型结论",
        "text": status_label_zh(ver.status),
        "color": status_color(ver.status),
    })
    return chain


def _claim_keywords(text: str) -> str:
    """简化：取主张中的数字 + 非停用词，作为"关键词"展示（与检索器同源思路）。"""
    import re
    nums = re.findall(r"\d+(?:\.\d+)?", text or "")
    return " · ".join(nums) if nums else "（见检索查询词）"


# ===== 改写建议（学术化谨慎改写，纯规则兜底 + LLM 文本透传）=====
# 规则映射：把"证明/证实"等强词替换为谨慎表述，保留证据边界。
_HEDGE_MAP = [
    ("证明", "现有证据提示"),
    ("证实", "现有研究支持"),
    ("显著提升", "提升（幅度待原文确认）"),
    ("必然", "可能"),
    ("绝对", "在特定条件下"),
]


def cautious_rewrite(text: str) -> str:
    """对强断言词做学术化谨慎改写（保留证据边界）。纯规则，不引入无依据结论。"""
    out = text or ""
    for strong, weak in _HEDGE_MAP:
        out = out.replace(strong, weak)
    return out


def export_report_markdown(r: DetectionReport) -> str:
    """导出结构化核查报告（Markdown）。

    包含：原文、整体可信度、风险论断、支持与反驳证据、模型共识、建议改写。
    纯文本，不联网，不编造。
    """
    conf = overall_confidence(r.verification)
    lines: List[str] = []
    lines.append(f"# 学术事实核查报告 {r.report_id}")
    lines.append("")
    lines.append(f"- 生成时间：{r.metadata.get('generated_at', 'N/A')}")
    lines.append(f"- 运行模式：{r.metadata.get('mode', 'N/A')}")
    lines.append(f"- 整体可信度：**{conf['score']}/100**（{conf['band_label']}）")
    lines.append("")
    lines.append("## 原文")
    lines.append("")
    lines.append("> " + (r.input_text or "").replace("\n", "\n> "))
    lines.append("")
    lines.append("## 风险论断（逐条）")
    lines.append("")
    ev_by_id = {e.id: e for e in r.evidence}
    for ver in r.verification:
        claim = next((c for c in r.claims if c.id == ver.claim_id), None)
        if claim is None:
            continue
        cons = consensus_level(ver)
        lines.append(f"### {claim.id} · {status_label_zh(ver.status)}（共识：{cons['label']}）")
        lines.append(f"- 原文：{claim.original_snippet}")
        lines.append(f"- 判定理由：{ver.rationale}")
        if ver.evidence_ids:
            lines.append("- 关联证据：")
            for eid in ver.evidence_ids:
                ev = ev_by_id.get(eid)
                if ev:
                    lines.append(f"  - [{ev.source_name}] {ev.title}（{ev.year or '年份未知'}） <{ev.url}>")
        lines.append("")
    lines.append("## 模型共识")
    lines.append("")
    for ver in r.verification:
        cons = consensus_level(ver)
        if cons["level"] == "low":
            lines.append(f"- **{ver.claim_id}** 存在分歧：{cons['note']}")
    lines.append("")
    lines.append("## 建议改写（谨慎化）")
    lines.append("")
    for corr in r.corrections:
        if corr.suggested_text:
            lines.append(f"- {corr.claim_id}：{corr.suggested_text}")
            lines.append(f"  - 原文：{corr.original_text}")
        else:
            lines.append(f"- {corr.claim_id}：（未生成自动改写，需人工依据证据）")
    lines.append("")
    lines.append("## 未解决问题")
    lines.append("")
    for u in r.unresolved:
        lines.append(f"- {u}")
    lines.append("")
    lines.append(
        "> 说明：本报告的“证据不足/暂无法核验”表示当前检索未找到可信证据，"
        "不等于该主张错误；“引用不存在”仅在 DOI 被精确查证且检索源明确查无时给出。"
    )
    return "\n".join(lines)
