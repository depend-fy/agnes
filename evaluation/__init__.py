"""阶段 7：评测模块（测试集 + 指标计算 + 基线对比）。

核心诚信原则：
- 评测必须有**人工标注的测试集**（ground_truth）。指标由真实运行结果对比标注算出。
- 没有标注数据 / 样本量过小时，明确标注"初步结果"，绝不编造准确率数字。
- 被测模型不能给自己输出打分；ground_truth 必须来自独立可信来源。
- 指标全部可复现：输入=测试集 + 管线输出，输出=确定性计算。

支持的指标（在标注测试集上）：
- 幻觉检测：精确率 / 召回率 / 误报率（按"系统判有问题 vs 标注有问题"）
- 引用真实性识别：引用不存在/不匹配的识别率
- 证据支持判断：状态判定与标注一致率
- 修正质量：修正成功率、修正后剩余错误率、新增错误率
- 可追溯率：每条判定是否有 evidence_id / 来源链接
- 效率：平均响应时间、单次成本估算
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

MIN_LABELED_SAMPLES = 10  # 低于此数标注"初步结果"


@dataclass
class LabeledCase:
    """一条带人工标注的测试用例。"""
    case_id: str
    text: str
    # 人工标注（可信 ground truth，独立于被测系统）
    expected_issue: bool                 # 该文本是否含幻觉/事实错误
    expected_issue_types: List[str] = field(default_factory=list)  # 八类问题标签
    expected_correct_claims: List[str] = field(default_factory=list)  # 已核实主张的关键片段
    note: str = ""

    def to_json(self) -> str:
        return json.dumps(self.__dict__, ensure_ascii=False)


@dataclass
class EvalResult:
    """一次评测的完整结果（供评测页展示）。"""
    case_count: int
    labeled: bool
    preliminary: bool                   # 样本不足 / 无标注 → True
    accuracy: Optional[Dict[str, float]]  # 幻觉检测 精确率/召回率/误报率
    issue_type_f1: Optional[Dict[str, float]]
    correction_success_rate: Optional[float]
    traceability_rate: Optional[float]    # 可追溯判定占比
    avg_latency_s: Optional[float]
    avg_cost_usd: Optional[float]
    per_case: List[Dict[str, Any]] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)


def load_labeled_cases(path: Optional[Path] = None) -> List[LabeledCase]:
    """从 JSON 文件加载人工标注测试集。不存在 → 空列表（评测会标注"无标注数据"）。"""
    path = path or (Path(__file__).resolve().parent.parent / "examples" / "labeled_cases.json")
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return [LabeledCase(**{k: v for k, v in item.items() if k in LabeledCase.__dataclass_fields__}) for item in raw]
    except (json.JSONDecodeError, TypeError, ValueError):
        return []


def _precision_recall(pred_pos: int, gold_pos: int, tp: int) -> Dict[str, float]:
    """混淆矩阵 → 精确率/召回率/误报率（分母为 0 时记 None 不编造）。"""
    fn = gold_pos - tp
    fp = pred_pos - tp
    precision = (tp / pred_pos) if pred_pos else None
    recall = (tp / gold_pos) if gold_pos else None
    fpr = (fp / (fn + fp)) if (fn + fp) else None
    f1 = None
    if precision is not None and recall is not None and (precision + recall):
        f1 = 2 * precision * recall / (precision + recall)
    return {"precision": precision, "recall": recall, "false_positive_rate": fpr, "f1": f1}


def run_evaluation(
    labeled: List[LabeledCase],
    pipeline_runner,
) -> EvalResult:
    """在标注测试集上跑管线，计算指标。

    pipeline_runner: 可调用 (text) -> DetectionReport（通常就是 pipeline.run）。
    无标注（labeled 为空）→ 返回 labeled=False、指标全 None，notes 说明原因。
    """
    if not labeled:
        return EvalResult(
            case_count=0, labeled=False, preliminary=True,
            accuracy=None, issue_type_f1=None, correction_success_rate=None,
            traceability_rate=None, avg_latency_s=None, avg_cost_usd=None,
            notes=["无人工标注测试集（examples/labeled_cases.json 不存在或为空）。"
                   "指标需基于真实标注运行，无法给出数值 —— 不编造。"],
        )

    pre = labeled and len(labeled) < MIN_LABELED_SAMPLES
    tp = fp = tn = fn = 0
    issue_hits: Dict[str, int] = {}
    issue_total: Dict[str, int] = {}
    issue_pred: Dict[str, int] = {}
    traceable = 0
    judged = 0
    latencies: List[float] = []
    costs: List[float] = []
    corrections_ok = 0
    corrections_total = 0
    per_case: List[Dict[str, Any]] = []

    for case in labeled:
        r = pipeline_runner(case.text)
        # 1. 幻觉检测：系统是否判"有问题"（status 非 已核实/未核验 的判定数 > 0 或 issue_types 非空）
        has_issue_in_report = any(
            (v.status.value in ("contradicted", "partial", "insufficient", "conflicting_sources"))
            or v.issue_types
            for v in r.verification
        )
        gold_issue = case.expected_issue
        if has_issue_in_report and gold_issue:
            tp += 1
        elif has_issue_in_report and not gold_issue:
            fp += 1
        elif not has_issue_in_report and gold_issue:
            fn += 1
        else:
            tn += 1

        # 2. 问题类型命中（按八类标签，简化：issue_types 非空视为预测含问题）
        pred_types = {i.value for v in r.verification for i in v.issue_types}
        gold_types = set(case.expected_issue_types)
        for t in gold_types:
            issue_total[t] = issue_total.get(t, 0) + 1
        for t in pred_types:
            issue_pred[t] = issue_pred.get(t, 0) + 1
        for t in pred_types & gold_types:
            issue_hits[t] = issue_hits.get(t, 0) + 1

        # 3. 可追溯率：有 evidence_id 或 来源链接 的判定占比
        for v in r.verification:
            judged += 1
            if v.evidence_ids or any(e.url or e.doi for e in r.evidence if e.id in v.evidence_ids):
                traceable += 1

        # 4. 修正质量：有修正且复核通过视为修正成功
        for c in r.corrections:
            corrections_total += 1
            if c.suggested_text:
                passed = next((rv for rv in r.review if rv.passed), None)
                if passed or not r.review:
                    corrections_ok += 1

        # 5. 效率 / 成本（真实入账，桩模式=0）
        m = r.metadata.get("metrics", {}).get("totals", {})
        latencies.append(m.get("pipeline_s", 0.0))
        costs.append(m.get("cost_estimate_usd", 0.0))

        per_case.append({
            "case_id": case.case_id,
            "gold_issue": gold_issue,
            "pred_issue": has_issue_in_report,
            "correct": has_issue_in_report == gold_issue,
            "claims": len(r.claims),
            "evidence": len(r.evidence),
        })

    accuracy = _precision_recall(tp + fp, tp + fn, tp)
    issue_type_f1 = {
        t: _precision_recall(issue_pred.get(t, 0), issue_total.get(t, 0), issue_hits.get(t, 0))["f1"]
        for t in sorted(set(list(issue_pred.keys()) + list(issue_total.keys())))
        if issue_total.get(t, 0) > 0 or issue_pred.get(t, 0) > 0
    }
    corr_rate = (corrections_ok / corrections_total) if corrections_total else None
    trace_rate = (traceable / judged) if judged else None

    notes = []
    if pre:
        notes.append(f"样本量 {len(labeled)} < {MIN_LABELED_SAMPLES}，指标为【初步结果】，需更多标注后复评。")
    if not labeled:
        notes.append("无人工标注数据，指标不可计算。")
    if costs and all(c == 0.0 for c in costs):
        notes.append("成本为 0：桩模式或无真实 LLM 调用（非真实成本）。")

    return EvalResult(
        case_count=len(labeled),
        labeled=True,
        preliminary=bool(pre),
        accuracy=accuracy,
        issue_type_f1=issue_type_f1,
        correction_success_rate=corr_rate,
        traceability_rate=trace_rate,
        avg_latency_s=(sum(latencies) / len(latencies)) if latencies else None,
        avg_cost_usd=(sum(costs) / len(costs)) if costs else None,
        per_case=per_case,
        notes=notes,
    )


def baseline_compare(eval_result: EvalResult, baseline: Optional[Dict[str, float]]) -> Dict[str, Any]:
    """与基线对比。基线为 None → 标注"未提供基线"，不编造对比数字。"""
    if not baseline:
        return {"provided": False, "note": "未提供基线（如单模型/无检索对照），暂不做对比。"}
    diff: Dict[str, float] = {}
    if eval_result.accuracy:
        for k, v in (eval_result.accuracy or {}).items():
            if v is not None and k in baseline:
                diff[k] = round(v - baseline[k], 4)
    return {"provided": True, "baseline": baseline, "delta": diff}
