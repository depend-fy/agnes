"""示例文本（阶段 2 预置案例，覆盖多种核验场景）。

每个案例含：
- id: 唯一标识
- title: 中文标题
- text: 待核验文本
- expected_summary: 预期核验结论（供人工对照，不作为系统判定）

覆盖场景：正确事实 / 虚构引用 / 数字错误 / 来源冲突
"""
from __future__ import annotations

SAMPLE_TEXTS = [
    {
        "id": "case_fictional_doi",
        "title": "虚构 DOI 案例",
        "text": (
            "某研究发表于 2023 年，DOI 为 10.xxxx/nonexistent-example，"
            "并证明该方法可以将准确率提高 40%。"
        ),
        "expected_summary": "DOI 10.xxxx/nonexistent-example 不存在，应识别为引用不存在。",
    },
    {
        "id": "case_numeric_error",
        "title": "数字错误案例",
        "text": (
            "根据 2023 年一篇发表于顶会的论文，该方法在标准数据集上"
            "将准确率提高了 120%（远超合理上限）。"
        ),
        "expected_summary": "120% 提升明显超出合理范围，应标记为数字异常。",
    },
    {
        "id": "case_source_conflict",
        "title": "来源冲突案例",
        "text": (
            "一项研究声称 X 方法效果优于 Y 方法，但另一项 2024 年研究"
            "在相同设置下得出相反结论。"
        ),
        "expected_summary": "两个可信来源结论矛盾，应标记为来源冲突。",
    },
    {
        "id": "case_correct_fact",
        "title": "正确事实案例",
        "text": "地球是太阳系八大行星之一，自转周期约为 24 小时。",
        "expected_summary": "天文常识，应全部已核实。",
    },
]


def get_sample_text(case_id: str) -> str:
    """按 id 取示例文本；找不到则返回空串。"""
    for s in SAMPLE_TEXTS:
        if s["id"] == case_id:
            return s["text"]
    return ""


def list_cases() -> list[dict]:
    return SAMPLE_TEXTS
