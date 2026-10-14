"""三角色提示词模板（结构化 JSON 输出）。

每个角色一个系统提示词 + 一个用户提示词构造器。
输出 schema 固定为 RoleJudgement 的 JSON 形态：
{
  "role": "fact_reviewer" | "evidence_reviewer" | "independent_reviewer",
  "judgement": "一句话判断",
  "confidence_note": "定性置信说明（不用伪精确概率）",
  "issues": ["issue_type", ...]
}
"""
from __future__ import annotations

import json
from typing import Any, Dict, List

SYSTEM_FACT = (
    "你是 VeriMind AI 的事实审查员。你的任务是审查给定的原子事实主张，"
    "判断其中哪些是可核验的事实、哪些是结论性陈述、哪些涉及元数据（DOI/年份/作者）。"
    "你只输出 JSON，格式为：\n"
    '{"role":"fact_reviewer","judgement":"...","confidence_note":"...","issues":[...]}\n'
    "issues 只能取以下值：fact_error, citation_not_exist, metadata_mismatch, "
    "citation_conclusion_mismatch, numeric_error, time_person_org_error, "
    "overreach_logic, missing_evidence, source_conflict。"
)

SYSTEM_EVIDENCE = (
    "你是 VeriMind AI 的证据审查员。你的任务是根据提供的证据来源，"
    "判断每条原子主张是否被证据真正支持。区分：直接支持 / 部分支持 / 反驳 / 无关。"
    "若证据不足，必须明确标注，不得臆测。你只输出 JSON，格式为：\n"
    '{"role":"evidence_reviewer","judgement":"...","confidence_note":"...","issues":[...]}\n'
    "issues 只能取：fact_error, citation_not_exist, metadata_mismatch, "
    "citation_conclusion_mismatch, numeric_error, time_person_org_error, "
    "overreach_logic, missing_evidence, source_conflict。"
)

SYSTEM_REVIEW = (
    "你是 VeriMind AI 的独立复核员。你的任务是独立检查前两个角色（事实审查员、证据审查员）"
    "的结论，关注：误报、证据不足、修正引入的新错误。你只输出 JSON，格式为：\n"
    '{"role":"independent_reviewer","judgement":"...","confidence_note":"...","issues":[...]}\n'
    "issues 只能取：fact_error, citation_not_exist, metadata_mismatch, "
    "citation_conclusion_mismatch, numeric_error, time_person_org_error, "
    "overreach_logic, missing_evidence, source_conflict。"
)


def build_user_prompt_factual(claims: List[Dict[str, Any]], text: str) -> str:
    """事实审查员的用户提示词。"""
    return (
        f"待核验文本：\n{text}\n\n"
        f"已提取的原子主张（JSON）：\n{json.dumps(claims, ensure_ascii=False, indent=2)}\n\n"
        "请逐条审查上述主张，输出结构化判断。"
    )


def _to_json_safe(objs) -> list:
    """把 Pydantic 模型列表转成 JSON 可序列化的 dict 列表。

    使用 model_dump(mode="json") 把 datetime / Enum 等转成 JSON 兼容类型，
    避免 json.dumps 报 datetime 不可序列化。
    """
    return [o.model_dump(mode="json") for o in objs]


def build_user_prompt_evidence(
    claims: List[Dict[str, Any]], evidence: List[Dict[str, Any]], text: str
) -> str:
    """证据审查员的用户提示词。"""
    return (
        f"待核验文本：\n{text}\n\n"
        f"已提取的原子主张（JSON）：\n{json.dumps(claims, ensure_ascii=False, indent=2)}\n\n"
        f"检索到的证据（JSON，可能为空）：\n{json.dumps(evidence, ensure_ascii=False, indent=2)}\n\n"
        "请判断每条主张与证据的支持关系，输出结构化判断。若证据为空或不足，必须标注。"
    )


def build_user_prompt_review(
    claims: List[Dict[str, Any]],
    evidence: List[Dict[str, Any]],
    corrections: List[Dict[str, Any]],
    prior_judgements: List[Dict[str, Any]],
) -> str:
    """独立复核员的用户提示词。"""
    return (
        f"待核验文本：\nclaims={json.dumps(claims, ensure_ascii=False)}\n"
        f"证据={json.dumps(evidence, ensure_ascii=False)}\n"
        f"前序角色判断={json.dumps(prior_judgements, ensure_ascii=False)}\n"
        f"修正记录={json.dumps(corrections, ensure_ascii=False)}\n\n"
        "请独立复核：是否误报、是否证据不足、修正是否引入新错误。输出结构化判断。"
    )
