"""VeriMind AI 检测工作台（最终成品布局）。

设计原则（界面优化）：
- 首页首屏只突出一个动作：粘贴文本 → 开始学术事实核查；技术说明收进折叠区。
- 结果页：整体可信度 + 逐句证据 放视觉中心；每条结论可展开看论文/时间/摘要/匹配原因。
- 多模型共识程度标识（高度一致 / 存在分歧 / 证据不足）；分歧时说明是哪句、哪些模型不同。
- 右侧窄模型栏，默认显结论+置信度，点击展开推理依据。
- 统一颜色语义：绿=有充分证据 / 黄=表述过度或证据有限 / 红=无法证实或疑似错误 / 灰=尚未检索到足够资料。
- 亮点功能：论断拆分 · 证据链可视化 · 引用真实性核验 · 证据时效性提示 · 模型分歧仲裁 · 可导出报告 · 改写建议。

运行：
    .venv\\Scripts\\python.exe -m streamlit run app/main.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st  # noqa: E402

from core.enums import ClaimStatus, IssueType, RoleType  # noqa: E402
from examples.sample_texts import list_cases  # noqa: E402
from pipeline import run as run_pipeline  # noqa: E402
from evaluation import load_labeled_cases, run_evaluation  # noqa: E402
from ui import (  # noqa: E402
    COLOR_GRAY,
    COLOR_GREEN,
    COLOR_RED,
    COLOR_YELLOW,
    cautious_rewrite,
    consensus_level,
    evidence_chain,
    export_report_markdown,
    overall_confidence,
    status_bg_color,
    status_color,
    status_label_zh,
)

st.set_page_config(page_title="智鉴 · VeriMind AI", page_icon="⚖", layout="wide")

# 注入自定义 CSS（颜色语义 + 卡片 + 评分环 + 证据链 + 窄侧栏）
_INJECT_CSS = """
<style>
  /* 首页首屏 */
  .vm-hero { text-align: center; padding: 18px 0 6px; }
  .vm-hero-title { font-size: 28px; font-weight: 700; color: #24292f; }
  .vm-hero-sub { font-size: 15px; color: #57606a; margin-top: 4px; }

  /* 整体可信度评分环 */
  .vm-score-card { display: flex; align-items: center; gap: 18px; padding: 14px 18px;
                   border-radius: 14px; background: #f6f8fa; border: 1px solid #d0d7de; }
  .vm-ring { width: 92px; height: 92px; border-radius: 50%; display: flex;
             align-items: center; justify-content: center; flex-shrink: 0; }
  .vm-ring-inner { width: 70px; height: 70px; border-radius: 50%; background: #fff;
                   display: flex; align-items: center; justify-content: center;
                   flex-direction: column; }
  .vm-ring-score { font-size: 24px; font-weight: 800; line-height: 1; }
  .vm-ring-max { font-size: 11px; color: #57606a; }
  .vm-band { display: inline-block; padding: 3px 10px; border-radius: 20px;
             font-size: 13px; font-weight: 600; color: #fff; }

  /* 逐句论断卡片 */
  .vm-claim { border-radius: 12px; padding: 12px 14px; margin: 8px 0;
              border: 1px solid #d0d7de; border-left-width: 5px; background: #fff; }
  .vm-claim-head { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
  .vm-claim-id { font-weight: 700; color: #24292f; }
  .vm-badge { padding: 2px 9px; border-radius: 12px; font-size: 12px; font-weight: 600; color: #fff; }
  .vm-consensus { font-size: 12px; font-weight: 600; padding: 2px 8px; border-radius: 10px; }
  .vm-claim-text { margin-top: 8px; padding: 6px 10px; border-radius: 8px;
                   background: #f6f8fa; font-size: 14px; }

  /* 证据链 */
  .vm-chain { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; margin-top: 8px; }
  .vm-chain-step { padding: 4px 10px; border-radius: 8px; font-size: 12px;
                   background: #f6f8fa; border: 1px solid #d0d7de; }
  .vm-chain-arrow { color: #57606a; font-weight: 700; }

  /* 窄侧栏模型卡 */
  .vm-models { border-radius: 12px; border: 1px solid #d0d7de; overflow: hidden; }
  .vm-model-row { padding: 10px 12px; border-bottom: 1px solid #eaeef2; }
  .vm-model-row:last-child { border-bottom: none; }
  .vm-model-role { font-weight: 700; font-size: 13px; }
  .vm-model-verdict { font-size: 12px; color: #57606a; margin-top: 2px; }

  /* 时效性提示 */
  .vm-freshness { font-size: 12px; padding: 4px 8px; border-radius: 6px; display: inline-block; }
  .vm-export { margin: 10px 0; }
</style>
"""
st.markdown(_INJECT_CSS, unsafe_allow_html=True)

from core.config import get_settings  # noqa: E402

_settings = get_settings()
_mode = _settings.mode


# ============================================================
# 首页首屏：单一动作
# ============================================================
st.markdown(
    '<div class="vm-hero">'
    '<div class="vm-hero-sub">多模型协同的学术事实核查与证据溯源系统</div>'
    '</div>',
    unsafe_allow_html=True,
)

with st.expander("系统配置与说明", expanded=False):
    _key_state = (
        f"Agnes 端点：{'已配置' if _settings.agnes and _settings.agnes.has_key else '未配置'} · "
        f"DeepSeek 端点：{'已配置' if _settings.deepseek and _settings.deepseek.has_key else '未配置'}"
    )
    st.caption(f"运行模式：{_mode}　·　{_key_state}")
    if _mode == "live":
        missing = []
        if not (_settings.agnes and _settings.agnes.has_key):
            missing.append("Agnes")
        if not (_settings.deepseek and _settings.deepseek.has_key):
            missing.append("DeepSeek")
        if missing:
            st.warning(
                f"live 模式下列端点未配置 API 密钥：{', '.join(missing)}。"
                "对应角色将降级为离线桩，报告中将如实标注，不会伪报为真实模型调用。"
            )
    st.markdown(
        "- **检索源**：Crossref、OpenAlex（公开接口，无需密钥）；检索失败时回退至本地预存证据快照。\n"
        "- **模型分工**：事实审查 → Agnes；证据审查 / 独立复核 → DeepSeek。\n"
        "- **判定原则**：缺乏证据时不判定为错误，仅标记为暂无法核验；不输出未经校准的概率数值；所有结论均可追溯至证据来源。"
    )

default_text = (
    "某研究发表于 2013 年，DOI 为 10.1038/nature12373，"
    "证明纳米级测温可将精度提高 40%。"
)
case_opts = ["（粘贴您的文本）"] + [c["title"] for c in list_cases()]
selected_case = st.selectbox("预置示例", case_opts, index=0)
input_text = st.text_area(
    "待核查文本",
    value=default_text,
    height=140,
    placeholder="粘贴需核查的 AI 生成内容、论文摘要或论断段落",
)
if selected_case != case_opts[0]:
    input_text = list_cases()[[c["title"] for c in list_cases()].index(selected_case)]["text"]

col_start, col_eval = st.columns([1, 1])
start = col_start.button("开始核查", type="primary", use_container_width=True)
run_eval = col_eval.button("运行评测", use_container_width=True)

if start:
    if not input_text.strip():
        st.error("请填写待核查文本。")
    else:
        with st.status("正在执行核查流程…", expanded=True) as status:
            status.write("流程：论断拆分 → 证据检索 → 多角色检测 → 证据匹配 → 修正建议 → 独立复核")
            report = run_pipeline(input_text)
            status.write(
                f"拆分 {len(report.claims)} 条论断 · 检索 {len(report.evidence)} 条证据 · "
                f"耗时 {report.metadata.get('total_pipeline_s', 0)} 秒"
            )
            status.update(label="核查完成", state="complete")
            st.session_state["report"] = report
            st.session_state.pop("eval_result", None)

if run_eval:
    with st.status("正在执行评测…", expanded=True) as ev_status:
        labeled = load_labeled_cases()
        ev_status.write(f"已加载 {len(labeled)} 条标注案例")
        eval_result = run_evaluation(labeled, pipeline_runner=run_pipeline)
        ev_status.update(label="评测完成", state="complete")
        st.session_state["eval_result"] = eval_result
        st.session_state.pop("report", None)


# ============================================================
# 结果页渲染函数
# ============================================================
def _render_report(r):
    """渲染完整检测报告（视觉中心：整体可信度 + 逐句证据 + 共识 + 证据链 + 窄侧栏 + 导出 + 改写）。"""
    st.divider()
    st.subheader("核查结果")

    # 视觉中心：整体可信度 + 逐句证据（两栏：主区 + 窄模型侧栏）
    main_col, side_col = st.columns([3, 1])
    with main_col:
        _render_overall_confidence(r)
        _render_claims(r)
    with side_col:
        _render_model_sidebar(r)

    # 可导出报告
    md = export_report_markdown(r)
    st.download_button("导出核查报告（Markdown）", data=md, file_name=f"{r.report_id}.md",
                       mime="text/markdown", key="export_md")

    # 改写建议（谨慎化）
    _render_rewrite_suggestions(r)

    # 模型分歧仲裁
    _render_arbitration(r)

    # 未解决问题
    if r.unresolved:
        st.markdown("### 未解决问题")
        for u in r.unresolved:
            st.warning(u)


def _render_overall_confidence(r):
    """整体可信度（快速判断）。"""
    conf = overall_confidence(r.verification)
    score = conf["score"]
    color = conf["band_color"]
    # 评分环（CSS conic-gradient 用色相，score 高=绿，中=黄，低=红/灰）
    ring_css = (
        f"background: conic-gradient({color} {score * 3.6}deg, #eaeef2 {score * 3.6}deg 360deg);"
    )
    st.markdown(
        f'<div class="vm-score-card">'
        f'<div class="vm-ring" style="{ring_css}">'
        f'<div class="vm-ring-inner"><div class="vm-ring-score" style="color:{color}">{score}</div>'
        f'<div class="vm-ring-max">/100</div></div></div>'
        f'<div><div class="vm-band" style="background:{color}">{conf["band_label"]}</div>'
        f'<div style="font-size:12px;color:#57606a;margin-top:6px">'
        f'基于 {len(r.verification)} 条论断的当前证据核验覆盖度（非文本为真概率）</div></div>'
        f'</div>',
        unsafe_allow_html=True,
    )
    # 状态分布小图
    st_count = {}
    for v in r.verification:
        st_count[v.status] = st_count.get(v.status, 0) + 1
    chips = []
    for s, n in st_count.items():
        c = status_color(s)
        chips.append(f'<span style="display:inline-block;padding:2px 8px;border-radius:10px;'
                     f'font-size:12px;color:{c};border:1px solid {c};margin-right:4px">'
                     f'{status_label_zh(s)} {n}</span>')
    st.markdown("".join(chips), unsafe_allow_html=True)


def _render_claims(r):
    """逐句论断（拆分 + 颜色语义 + 可展开证据链/论文/摘要/匹配原因/共识）。"""
    ev_by_id = {e.id: e for e in r.evidence}
    st.markdown("### 逐条论断拆分与证据溯源")
    for c in r.claims:
        vr = next((v for v in r.verification if v.claim_id == c.id), None)
        status = vr.status if vr else c.status
        color = status_color(status)
        bg = status_bg_color(status)
        cons = consensus_level(vr) if vr else {"level": "insufficient", "color": COLOR_GRAY,
                                                "label": "证据不足", "divergent_roles": [], "note": "无角色判断"}
        # 卡片头
        st.markdown(
            f'<div class="vm-claim" style="border-left-color:{color};background:{bg}22">'
            f'<div class="vm-claim-head">'
            f'<span class="vm-claim-id">{c.id}</span>'
            f'<span class="vm-badge" style="background:{color}">{status_label_zh(status)}</span>'
            f'<span class="vm-consensus" style="color:{cons["color"]};border:1px solid {cons["color"]}">'
            f'共识：{cons["label"]}</span>'
            f'</div>'
            f'<div class="vm-claim-text">{c.original_snippet}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )
        # 可展开：检索论文 / 时间 / 摘要 / 匹配原因
        with st.expander(f"证据链与匹配原因（{len(vr.evidence_ids) if vr else 0} 条证据）", expanded=False):
            if vr and vr.rationale:
                st.markdown(f"**判定理由：** {vr.rationale}")
            if vr and vr.issue_types:
                st.markdown("**问题类型：** " + " · ".join(_issue_label(i) for i in vr.issue_types))
            chain = evidence_chain(c, vr, r.evidence) if vr else []
            if any(s["step"] in ("检索论文", "原文依据") for s in chain):
                _render_evidence_chain(chain)
            # 关联论文明细（含时效性提示）
            if vr and vr.evidence_ids:
                for eid in vr.evidence_ids:
                    ev = ev_by_id.get(eid)
                    if ev:
                        _render_evidence_detail(ev)
            # 分歧仲裁说明
            if cons["level"] == "low":
                st.markdown(f'**模型分歧**：{cons["note"]}。仲裁依据：引用质量 + 证据数量 + 来源等级。')


def _render_evidence_chain(chain):
    """证据链可视化：论断 → 关键词 → 检索论文 → 原文依据 → 多模型结论。"""
    st.markdown("**证据链：**")
    parts = []
    for s in chain:
        if s["step"] == "多模型结论":
            parts.append(f'<span class="vm-chain-step" style="color:{s.get("color", COLOR_GRAY)};'
                         f'font-weight:700">{s["step"]}：{s["text"]}</span>')
        elif s["step"] == "检索论文":
            yr = f"（{s['year']}）" if s.get("year") else ""
            parts.append(f'<span class="vm-chain-step" title="{s.get("url", "")}">'
                         f'{s["step"]}：{s["text"][:30]}{yr}</span>')
        elif s["step"] == "原文依据":
            parts.append(f'<span class="vm-chain-step" title="{s["text"]}">'
                         f'{s["step"]}：{s["text"][:24]}…</span>')
        else:
            parts.append(f'<span class="vm-chain-step">{s["step"]}：{s["text"]}</span>')
        parts.append('<span class="vm-chain-arrow">→</span>')
    if parts:
        parts.pop()  # 去掉末尾箭头
        st.markdown('<div class="vm-chain">' + "".join(parts) + "</div>", unsafe_allow_html=True)


def _render_evidence_detail(ev):
    """单条论文：来源 / DOI / 时间 / 摘要 / 时效性提示。"""
    meta_bits = []
    if ev.doi:
        meta_bits.append(f"DOI {ev.doi}")
    if ev.year:
        meta_bits.append(f"{ev.year} 年")
    if ev.authors:
        meta_bits.append("，".join(ev.authors[:4]))
    fresh = _freshness_hint(ev.year)
    tier = getattr(ev, "source_tier", "academic")
    tier_badge = _tier_badge_html(tier)
    st.markdown(
        f'<div class="vm-evidence" style="padding:8px 10px;border-radius:8px;background:#f6f8fa;'
        f'border:1px solid #d0d7de;margin:6px 0;font-size:13px"'
        f' data-tier="{tier}">'
        f'{tier_badge} <b>{ev.source_name}</b> · {" · ".join(meta_bits)} '
        f'<span class="vm-freshness" style="background:{fresh["bg"]};color:{fresh["color"]};margin-left:6px">'
        f'{fresh["label"]}</span><br>'
        f'<span style="color:#57606a">{ev.title}</span>'
        f'<br><a href="{ev.url}" target="_blank" style="font-size:12px">{ev.url}</a>'
        f'{"<br><i>摘要片段：" + ev.snippet[:200] + "…</i>" if ev.snippet else ""}'
        f'</div>',
        unsafe_allow_html=True,
    )


def _tier_badge_html(tier: str) -> str:
    """证据来源等级徽章：学术=绿边 / Wikipedia=黄边 / 普通网页=灰边+仅供参考。"""
    if tier == "academic":
        color, label = COLOR_GREEN, "学术证据"
        extra = ""
    elif tier == "wikipedia":
        color, label = COLOR_YELLOW, "权威词条"
        extra = ""
    else:  # web
        color, label = COLOR_GRAY, "普通网页"
        extra = "<span style='font-size:11px;color:#57606a;margin-left:4px'>仅供参考，不用于升级判定</span>"
    return (
        f'<span style="display:inline-block;padding:1px 8px;border-radius:10px;font-size:12px;'
        f'color:{color};border:1px solid {color};margin-right:6px">{label}</span>{extra}'
    )


def _freshness_hint(year):
    """证据时效性提示（医学/AI 等更新快领域）。"""
    if not year:
        return {"label": "年份未知", "color": COLOR_GRAY, "bg": status_bg_color(ClaimStatus.UNVERIFIABLE)}
    import datetime
    age = datetime.datetime.now().year - year
    if age <= 2:
        return {"label": f"较新（{year}）", "color": COLOR_GREEN, "bg": "#dafbe0"}
    if age <= 5:
        return {"label": f"较旧（{year}，{age} 年前）", "color": COLOR_YELLOW, "bg": "#fff8c5"}
    return {"label": f"较早（{year}，{age} 年前，可能被更新研究补充）", "color": COLOR_GRAY, "bg": "#eaeef2"}


def _render_model_sidebar(r):
    """右侧窄模型栏：默认显结论+置信度，点击展开推理依据。"""
    st.markdown("### 多模型判定")
    providers = r.metadata.get("providers", {})
    # 按角色分组 judgement
    js_by_role: dict = {}
    for v in r.verification:
        for j in v.role_judgements:
            js_by_role.setdefault(j.role.value, []).append(j)
    # 汇总每个角色的代表判断（取首个 claim 的）
    rep = {}
    for role_val, js in js_by_role.items():
        rep[role_val] = js[0]
    st.markdown(
        '<div class="vm-models">' + "".join(
            _model_row_html(role_val, rep[role_val]) for role_val in rep
        ) + "</div>",
        unsafe_allow_html=True,
    )
    # 点击展开每个角色的完整推理依据
    for role_val in rep:
        with st.expander(f"展开 {role_val} 的推理依据", expanded=False):
            for j in js_by_role.get(role_val, []):
                tag_note = "（桩/模拟）" if j.model_tag == "stub" else f"（{j.model_tag}）"
                st.markdown(f"- {j.judgement} {tag_note}")
                if j.confidence_note:
                    st.caption(f"置信度：{j.confidence_note}")
    # 模型分配
    if providers:
        for role_name, tag in providers.items():
            label = "离线桩（模拟）" if tag == "stub" else f"真实模型 {tag}"
            st.caption(f"- {role_name} → {label}")


def _model_row_html(role_val, j):
    """窄侧栏单行：角色 + 简短结论 + 置信度。"""
    short = j.judgement[:40] + ("…" if len(j.judgement) > 40 else "")
    color = COLOR_GRAY if j.model_tag == "stub" else COLOR_GREEN
    return (
        f'<div class="vm-model-row">'
        f'<div class="vm-model-role">{role_val}</div>'
        f'<div class="vm-model-verdict" style="color:{color}">{short}</div>'
        f'<div style="font-size:11px;color:#57606a">置信度：{j.confidence_note[:30]}</div>'
        f'</div>'
    )


def _render_rewrite_suggestions(r):
    """改写建议（学术化谨慎化，保留证据边界）。"""
    st.markdown("### 改写建议")
    if r.corrections:
        for corr in r.corrections:
            if corr.suggested_text:
                st.markdown(f"**{corr.claim_id}** 建议改写：")
                st.markdown(f"- 原文：{corr.original_text}")
                st.markdown(f"- 改写：{corr.suggested_text}")
                if corr.preserved_parts:
                    st.caption("保留的已支持部分：" + " · ".join(corr.preserved_parts))
            else:
                # 离线桩：给规则兜底的谨慎改写（把“证明”等强词换掉）
                suggested = cautious_rewrite(corr.original_text)
                st.markdown(f"**{corr.claim_id}** 规则改写（离线桩，未经 LLM）：")
                st.markdown(f"- 原文：{corr.original_text}")
                st.markdown(f"- 改写：{suggested}")
                st.caption("（离线桩未生成 LLM 改写，上为规则替换强词；需人工依据证据确认）")
    else:
        st.caption("当前无可改写主张（无证据或主张已核实/暂无法核验，不强行修改以避免编造）。")


def _render_arbitration(r):
    """模型分歧仲裁：不强行平均，按引用质量+证据数量+来源等级。"""
    divs = [v for v in r.verification if consensus_level(v)["level"] == "low"]
    if not divs:
        st.markdown("### 模型分歧仲裁")
        st.caption("未发现模型间结论分歧。")
        return
    st.markdown("### 模型分歧仲裁")
    for v in divs:
        cons = consensus_level(v)
        st.markdown(f"**{v.claim_id}** 存在分歧：{cons['note']}")
        st.markdown(
            f"仲裁结论：**{status_label_zh(v.status)}**（依据：引用质量 + 证据数量 + 来源等级，"
            f"不强行平均）。关联证据 {len(v.evidence_ids)} 条。"
        )


def _render_eval(ev):
    """渲染评测结果（指标 + 初步结果标注）。"""
    st.divider()
    st.subheader("评测结果（标注测试集）")
    if ev.labeled:
        if ev.preliminary:
            st.warning("以下为【初步结果】—— 标注样本量不足，需更多数据后复评。")
        st.caption(
            f"案例数 {ev.case_count} · 平均延迟 {ev.avg_latency_s if ev.avg_latency_s is not None else 'N/A'}s · "
            f"平均成本 {ev.avg_cost_usd if ev.avg_cost_usd is not None else 'N/A'} USD"
        )
        if ev.accuracy:
            acc = ev.accuracy
            a1, a2, a3, a4 = st.columns(4)
            a1.metric("精确率", _fmt(acc["precision"]))
            a2.metric("召回率", _fmt(acc["recall"]))
            a3.metric("误报率", _fmt(acc["false_positive_rate"]))
            a4.metric("F1", _fmt(acc["f1"]))
        if ev.correction_success_rate is not None:
            st.markdown(f"**修正成功率：** {ev.correction_success_rate:.2f}")
        if ev.traceability_rate is not None:
            st.markdown(f"**证据可追溯率：** {ev.traceability_rate:.2f}")
        if ev.issue_type_f1:
            st.markdown("**各问题类型 F1：**")
            for t, f1 in ev.issue_type_f1.items():
                st.caption(f"- {t}: {_fmt(f1)}")
        st.markdown("**逐案例结果：**")
        for c in ev.per_case:
            mark = "通过" if c["correct"] else "未通过"
            st.markdown(
                f"{mark} {c['case_id']} · 标注{'有问题' if c['gold_issue'] else '无问题'} · "
                f"系统{'判有问题' if c['pred_issue'] else '判无问题'} · "
                f"主张{c['claims']} 证据{c['evidence']}"
            )
    else:
        st.info("无人工标注测试集，指标不可计算。")
        for n in ev.notes:
            st.caption(n)
    if ev.notes:
        with st.expander("评测说明"):
            for n in ev.notes:
                st.caption(n)


def _issue_label(i):
    """IssueType → 中文标签。"""
    return {
        IssueType.FACT_ERROR: "事实错误",
        IssueType.CITATION_NOT_EXIST: "引用不存在（已查证查无）",
        IssueType.METADATA_MISMATCH: "元数据不匹配",
        IssueType.CITATION_CONCLUSION_MISMATCH: "引用与结论不匹配",
        IssueType.NUMERIC_ERROR: "数字存疑（摘要未确认）",
        IssueType.TIME_PERSON_ORG_ERROR: "时间/人物/机构错误",
        IssueType.OVERREACH_LOGIC: "逻辑推断过度",
        IssueType.MISSING_EVIDENCE: "缺少必要证据（等待核实）",
        IssueType.SOURCE_CONFLICT: "来源冲突",
    }.get(i, i.value)


def _fmt(v):
    """指标数值格式化：None → 'N/A'（不编造数字）。"""
    if v is None:
        return "N/A（分母为 0，不编造）"
    return f"{v:.3f}"


# ============================================================
# 结果页渲染
# ============================================================
if "report" in st.session_state:
    _render_report(st.session_state["report"])

if "eval_result" in st.session_state:
    _render_eval(st.session_state["eval_result"])
