"""证据快照：现场演示的离线兜底机制。

设计理由：
- 比赛现场网络不可靠，Crossref/OpenAlex 可能限流/超时。
- 若检索失败或网络不可达，可从本地 JSON 快照加载预取好的证据，
  保证 Demo 不卡死、不崩，且能继续走完"分类 → 修正 → 复核 → 报告"链路。
- 快照来源：在联网环境下对演示案例实际检索一次，把 Evidence.model_dump(mode="json")
  存成 JSON；现场断网时加载它。
- 明确标注：快照是"预取证据"，检索时间戳保留原始值，报告里会提示来源为快照。

用法：
    from retrieval.snapshot import load_snapshot, save_snapshot, retrieve_with_fallback
    evidence = retrieve_with_fallback(claims, live_search_fn, snapshot_path)
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional

from core.models import Evidence

DEFAULT_SNAPSHOT_PATH = Path(__file__).resolve().parent.parent / "examples" / "evidence_snapshot.json"


def save_snapshot(evidence: List[Evidence], path: Optional[Path] = None) -> None:
    """把真实检索到的证据存为快照 JSON（联网环境预取时调用）。"""
    path = path or DEFAULT_SNAPSHOT_PATH
    payload = {
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "count": len(evidence),
        "evidence": [e.model_dump(mode="json") for e in evidence],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_snapshot(path: Optional[Path] = None) -> List[Evidence]:
    """从快照 JSON 加载证据（现场断网时调用）。无快照返回空列表。"""
    path = path or DEFAULT_SNAPSHOT_PATH
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        items = payload.get("evidence", []) if isinstance(payload, dict) else payload
        out: List[Evidence] = []
        for it in items:
            # retrieved_at 在快照里是 ISO 字符串，Evidence 模型期望 datetime
            if isinstance(it.get("retrieved_at"), str):
                it["retrieved_at"] = datetime.fromisoformat(it["retrieved_at"])
            out.append(Evidence.model_validate(it))
        return out
    except (json.JSONDecodeError, KeyError, ValueError):
        return []


def retrieve_with_fallback(
    claims,
    live_search_fn: Callable[[], List[Evidence]],
    snapshot_path: Optional[Path] = None,
    require_network: bool = True,
) -> Dict[str, object]:
    """先尝试真实检索；失败/空且允许兜底时，从快照加载。

    返回 {evidence, source}，source ∈ {"live", "snapshot", "none"}。
    - 真实检索到证据 → source="live"。
    - 真实检索失败/为空 且 快照有内容 → source="snapshot"。
    - 都没有 → source="none"。

    注意：快照是兜底，不能谎称是"刚检索到的"。source 会写进报告 metadata，
    报告页据此标注"证据来源：预取快照"。
    """
    try:
        live = live_search_fn()
        if live:
            return {"evidence": live, "source": "live"}
    except Exception:
        live = []

    if not require_network:
        return {"evidence": live, "source": "live" if live else "none"}

    snap = load_snapshot(snapshot_path)
    if snap:
        return {"evidence": snap, "source": "snapshot"}
    return {"evidence": live, "source": "none"}
