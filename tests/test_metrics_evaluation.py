"""阶段 7 测试：成本/延迟统计 + 评测模块（离线确定性，不编造数字）。"""
from evaluation import EvalResult, LabeledCase, run_evaluation, baseline_compare
from metrics import build_metrics, estimate_cost, collect_provider_stats


# ---------- metrics ----------

def test_estimate_cost_known_model():
    # deepseek: 1K in = $0.0003, 1K out = $0.0012 → 1000 in + 1000 out
    c = estimate_cost(1000, 1000, "deepseek-flash")
    assert abs(c - 0.0015) < 1e-9


def test_estimate_cost_unknown_model_is_zero_not_fabricated():
    c = estimate_cost(5000, 5000, "some_unknown_model_xyz")
    assert c == 0.0  # 无单价 → 0，不编造


def test_build_metrics_stub_zero_cost():
    stats = [
        {"role": "fact_reviewer", "provider": "stub", "model_tag": "stub",
         "calls_made": 1, "total_tokens_in": 0, "total_tokens_out": 0, "total_latency_s": 0.0},
    ]
    m = build_metrics(stats, pipeline_s=1.5, retrieval_s=0.3)
    assert m["totals"]["cost_estimate_usd"] == 0.0
    assert m["totals"]["pipeline_s"] == 1.5
    assert m["cost_is_estimate"] is True


def test_build_metrics_flags_missing_price():
    stats = [
        {"role": "ev", "provider": "x", "model_tag": "weird_model_no_price",
         "calls_made": 1, "total_tokens_in": 1000, "total_tokens_out": 1000, "total_latency_s": 2.0},
    ]
    m = build_metrics(stats, pipeline_s=3.0)
    assert m["totals"]["cost_estimate_usd"] == 0.0
    # 有 token 但无单价 → 必须有明确标注，不能悄悄记 0 当真实成本
    assert any("单价未配置" in n for n in m["notes"])


def test_collect_provider_stats_stub():
    class Stub:
        name = "stub"
        model_tag = "stub"
        calls_made = 0
    stats = collect_provider_stats({"fact_reviewer": Stub()})
    assert stats[0]["total_tokens_in"] == 0


# ---------- evaluation ----------

def test_run_evaluation_no_labeled_data():
    r = run_evaluation(labeled=[], pipeline_runner=lambda t: None)
    assert r.labeled is False
    assert r.preliminary is True
    assert r.accuracy is None
    assert any("无" in n or "人工标注" in n for n in r.notes)


def test_run_evaluation_small_sample_flagged_preliminary():
    # 2 条标注 < MIN_LABELED_SAMPLES(10) → 标注"初步结果"，但指标仍按真实运行计算
    r2 = run_evaluation(
        labeled=[
            LabeledCase(case_id="a", text="t", expected_issue=False, expected_issue_types=[]),
            LabeledCase(case_id="b", text="t", expected_issue=False, expected_issue_types=[]),
        ],
        pipeline_runner=lambda t: _make_report(have_issue=False),
    )
    assert r2.labeled is True
    assert r2.preliminary is True  # 样本 < 10
    assert any("初步结果" in n for n in r2.notes)
    # 两条都没问题且预测也没问题 → 召回率分母为 0，应记 None 不编造
    assert r2.accuracy is not None
    assert r2.accuracy["recall"] is None


def _make_report(have_issue: bool):
    """构造最小 DetectionReport 替身，满足 run_evaluation 访问的字段。"""
    from types import SimpleNamespace
    status_val = "insufficient" if have_issue else "unverifiable"
    issue_types = [SimpleNamespace(value="numeric_error")] if have_issue else []

    class _V:
        def __init__(self):
            self.status = SimpleNamespace(value=status_val)
            self.issue_types = issue_types
            self.evidence_ids = []

    rep = SimpleNamespace(
        verification=[_V()],
        claims=[],
        evidence=[],
        corrections=[],
        review=[],
        metadata={"metrics": {"totals": {"pipeline_s": 1.0, "cost_estimate_usd": 0.0}}},
    )
    return rep


def test_baseline_compare_no_baseline():
    r = run_evaluation([], lambda t: None)
    res = baseline_compare(r, None)
    assert res["provided"] is False


def test_baseline_compare_with_baseline():
    r = run_evaluation([], lambda t: None)
    res = baseline_compare(r, {"precision": 0.5})
    assert res["provided"] is True
    assert res["baseline"] == {"precision": 0.5}
