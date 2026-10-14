"""阶段 7：成本 / 延迟 / token 统计（真实入账，不编造）。

设计原则：
- 成本 = Σ(每次调用 token_in × 单价_in + token_out × 单价_out)。
- 单价来自 PRICE_TABLE（按模型名，美元/1K token）。表中没有的模型 → cost_estimate 记 0，
  并在 note 里标注"单价未配置"，绝不编造一个数字。
- 延迟 / token 来自 provider 累计的真实调用统计（openai_compat._accumulate），
  桩模式为 0（桩不调用 LLM，真实成本=0）。
- 结果以 dict 形式写入 report.metadata["metrics"]，供评测页展示。

用法：
    from metrics import summarize_metrics, build_metrics
    provider_stats = [...]   # 每个 provider 的累计统计
    report.metadata["metrics"] = build_metrics(provider_stats, pipeline_s)
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

# 美元 / 1K token。仅列可查的常见价格作为"量级估计"；未知模型一律 0 + 标注。
# 注意：这些是"量级参考"，实际账单以厂商为准；报告里会标注 estimate。
PRICE_TABLE: Dict[str, Dict[str, float]] = {
    # 示例（可按需更新）。DeepSeek 价格低，Agnes 按其定价。
    "deepseek": {
        "in": 0.0003,    # 美元/1K 输入 token
        "out": 0.0012,   # 美元/1K 输出 token
    },
    "agnes-3.0-flash": {
        "in": 0.0005,
        "out": 0.0015,
    },
}


def _price(model_tag: str) -> Dict[str, float]:
    """按 model_tag 找单价；找不到返回 0（不编造）。"""
    for key, p in PRICE_TABLE.items():
        if key in model_tag.lower():
            return p
    return {"in": 0.0, "out": 0.0}


def estimate_cost(tokens_in: int, tokens_out: int, model_tag: str) -> float:
    """单次/累计 token 成本估算（美元）。未知模型 → 0。"""
    p = _price(model_tag)
    return round((tokens_in * p["in"] + tokens_out * p["out"]) / 1000.0, 6)


def build_metrics(
    provider_stats: List[Dict[str, Any]],
    pipeline_s: float,
    retrieval_s: float = 0.0,
) -> Dict[str, Any]:
    """把各 provider 的累计统计 + 管线耗时 汇总成 metrics dict。

    provider_stats 每项：{role, provider, model_tag, calls_made,
                          total_tokens_in, total_tokens_out, total_latency_s}
    """
    per_provider: List[Dict[str, Any]] = []
    tot_in = tot_out = 0
    tot_cost = 0.0
    tot_llm_latency = 0.0
    tot_calls = 0
    price_missing: set[str] = set()

    for st in provider_stats:
        model_tag = st.get("model_tag", "")
        tokens_in = st.get("total_tokens_in", 0)
        tokens_out = st.get("total_tokens_out", 0)
        cost = estimate_cost(tokens_in, tokens_out, model_tag)
        if tokens_in + tokens_out > 0 and _price(model_tag) in ({"in": 0.0, "out": 0.0},):
            # 有 token 但无单价 → 标注缺失，不编造
            price_missing.add(model_tag or "unknown")
        tot_in += tokens_in
        tot_out += tokens_out
        tot_cost += cost
        tot_llm_latency += st.get("total_latency_s", 0.0)
        tot_calls += st.get("calls_made", 0)
        per_provider.append({
            **st,
            "cost_estimate": cost,
            "price_configured": not (tokens_in + tokens_out > 0 and model_tag in price_missing),
        })

    notes = []
    if price_missing:
        notes.append(f"以下模型单价未配置，成本按 0 计（非真实 0 成本）：{sorted(price_missing)}")
    if tot_in + tot_out == 0 and tot_calls > 0:
        notes.append("桩模式或 LLM 调用失败：无真实 token，成本=0")

    return {
        "per_provider": per_provider,
        "totals": {
            "llm_calls": tot_calls,
            "tokens_in": tot_in,
            "tokens_out": tot_out,
            "cost_estimate_usd": round(tot_cost, 6),
            "llm_latency_s": round(tot_llm_latency, 3),
            "retrieval_s": round(retrieval_s, 3),
            "pipeline_s": round(pipeline_s, 3),
        },
        "cost_is_estimate": True,   # 始终是量级估算，非账单
        "notes": notes,
    }


def collect_provider_stats(providers: Dict[str, Any]) -> List[Dict[str, Any]]:
    """从 provider 对象（OpenAICompatClient）提取累计统计。

    桩 provider（无 total_* 字段）返回全 0。
    """
    out: List[Dict[str, Any]] = []
    for role, p in providers.items():
        out.append({
            "role": getattr(role, "value", str(role)),
            "provider": getattr(p, "name", "unknown"),
            "model_tag": getattr(p, "model_tag", "stub"),
            "calls_made": getattr(p, "calls_made", 0),
            "total_tokens_in": getattr(p, "total_tokens_in", 0),
            "total_tokens_out": getattr(p, "total_tokens_out", 0),
            "total_latency_s": getattr(p, "total_latency_s", 0.0),
        })
    return out
