"""现场演示辅助：一条命令跑通可重复演示案例并输出摘要。

设计理由：
- 比赛现场用一条命令复现核心案例，避免手点 UI 出错。
- 默认 live；网络不可达时自动回退证据快照（retrieval 层已内置），
  若某 LLM 失败对应角色降级为桩（不崩、不编造）。
- 打印每个案例的：主张数 / 证据数 / 证据来源 / 各状态计数 / 修正数 / 复核通过数 / 未解决数。

用法（在 verimind 目录）：
    .venv\\Scripts\\python.exe -m examples.demo_runner
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from examples.sample_texts import list_cases  # noqa: E402
from pipeline import run  # noqa: E402

# 阶段 7：补充主案例“真实 DOI”（完整链路演示），与 demo_cases.json 对齐
_EXTRA_CASES = [
    {
        "id": "case_real_doi",
        "title": "真实 DOI（完整链路演示）",
        "text": "某研究发表于 2013 年，DOI 为 10.1038/nature12373，证明纳米级测温可将精度提高 40%。",
    },
]


def _all_cases() -> list:
    merged = list_cases() + _EXTRA_CASES
    return merged


DEMO_CASE_IDS = [
    "case_fictional_doi",   # 虚构 DOI
    "case_numeric_error",   # 数字错误
    "case_source_conflict", # 来源冲突
    "case_correct_fact",    # 正确事实
]

def summarize(report) -> None:
    counts = report.metadata.get("status_counts", {})
    m = report.metadata.get("metrics", {}).get("totals", {})
    print(f"  主张 {len(report.claims)} | 证据 {len(report.evidence)}（{report.metadata.get('evidence_source', 'n/a')}）| 修正 {len(report.corrections)} | 复核 {len(report.review)} | 未解决 {len(report.unresolved)}")
    non_zero = {k: v for k, v in counts.items() if v}
    print(f"  状态分布：{non_zero or '无'}")
    print(f"  成本估算 {m.get('cost_estimate_usd', 0)} USD · token {m.get('tokens_in', 0)}/{m.get('tokens_out', 0)} · 管线 {m.get('pipeline_s', 0)}s")


def main() -> None:
    print("=== VeriMind AI 现场演示（可重复案例）===")
    for case in _all_cases():
        if case["id"] not in DEMO_CASE_IDS and case["id"] not in (c["id"] for c in _EXTRA_CASES):
            continue
        print(f"\n【{case['title']}】")
        print(f"  文本：{case['text'][:60]}…")
        report = run(case["text"])
        summarize(report)


if __name__ == "__main__":
    main()
