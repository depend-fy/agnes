"""阶段 2/4/5/6 测试：报告组装与端到端管线。

说明：阶段 4 后管线会做真实检索（网络可达时证据非空、状态会升级），
阶段 5 后会基于证据生成修正与复核。因此本文件的断言只验证**不变量**
（结构、可 JSON 化、空输入行为），不对具体数量做死断言。
"""
import json

from pipeline import run


def test_pipeline_returns_report():
    r = run("某研究发表于 2023 年，DOI 为 10.1/abc，准确率提高 40%。")
    assert r.report_id.startswith("RPT-")
    assert len(r.claims) >= 1
    assert len(r.verification) == len(r.claims)
    # 修正/复核是 1:1 对应可修正主张，数量 <= 主张数（不变量）
    assert len(r.corrections) <= len(r.claims)
    assert len(r.review) == len(r.corrections)
    # 任意网络状态下都可 JSON 化
    json.dumps(r.model_dump(mode="json"), ensure_ascii=False)


def test_pipeline_status_counts():
    r = run("准确率提高 40%。")
    counts = r.metadata["status_counts"]
    # 各状态计数为非负整数；总数 == verification 条数（不变量）
    assert all(isinstance(v, int) and v >= 0 for v in counts.values())
    assert sum(v for v in counts.values() if v) == len(r.verification)


def test_pipeline_unresolved_is_subset():
    r = run("某研究 DOI 为 10.1/abc。")
    # unresolved 只包含"未解决"的主张 + 复核失败项，不会超过 主张数 + 复核项数
    assert isinstance(r.unresolved, list)
    max_expected = len(r.verification) + len(r.review)
    assert len(r.unresolved) <= max_expected


def test_pipeline_empty_text():
    r = run("")
    assert r.claims == []
    assert r.verification == []
    assert r.metadata["claim_count"] == 0
    assert r.corrections == []
    assert r.review == []


def test_report_json_serializable():
    """DetectionReport 必须可 JSON 序列化（供持久化 / API 输出）。"""
    r = run("准确率提高 40%。")
    s = json.dumps(r.model_dump(mode="json"), ensure_ascii=False)
    assert "report_id" in s


def test_pipeline_evidence_source_recorded():
    """阶段 6：报告必须记录证据来源（live / snapshot / none），供报告页标注。"""
    r = run("某研究 DOI 为 10.1/abc。")
    assert r.metadata.get("evidence_source") in ("live", "snapshot", "none")
