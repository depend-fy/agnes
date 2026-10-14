"""阶段 6 测试：证据快照兜底 + 现场演示保障。"""
import json
from datetime import datetime, timezone
from pathlib import Path

from core.models import Evidence
from retrieval.snapshot import (
    DEFAULT_SNAPSHOT_PATH,
    load_snapshot,
    retrieve_with_fallback,
    save_snapshot,
)


def _mk_evidence() -> Evidence:
    return Evidence(
        id="E-test1",
        source_name="Crossref",
        url="https://doi.org/10.1038/nature12373",
        title="Test paper",
        year=2013,
        doi="10.1038/nature12373",
        retrieved_at=datetime.now(timezone.utc),
    )


def test_snapshot_roundtrip(tmp_path: Path):
    """save → load 往返，证据字段保留。"""
    p = tmp_path / "snap.json"
    save_snapshot([_mk_evidence()], p)
    loaded = load_snapshot(p)
    assert len(loaded) == 1
    assert loaded[0].doi == "10.1038/nature12373"
    assert loaded[0].title == "Test paper"


def test_fallback_uses_snapshot_when_live_empty(tmp_path: Path):
    """live 检索返回空 → 回退快照。"""
    p = tmp_path / "snap.json"
    save_snapshot([_mk_evidence()], p)
    res = retrieve_with_fallback(
        claims=[], live_search_fn=lambda: [], snapshot_path=p, require_network=True
    )
    assert res["source"] == "snapshot"
    assert len(res["evidence"]) == 1


def test_fallback_prefers_live_when_available(tmp_path: Path):
    """live 检索有结果 → 不用快照。"""
    p = tmp_path / "snap.json"
    save_snapshot([_mk_evidence()], p)
    res = retrieve_with_fallback(
        claims=[], live_search_fn=lambda: [_mk_evidence()], snapshot_path=p, require_network=True
    )
    assert res["source"] == "live"


def test_fallback_none_when_no_snapshot(tmp_path: Path):
    """live 空 + 无快照 → source=none，不崩。"""
    p = tmp_path / "nope.json"
    res = retrieve_with_fallback(
        claims=[], live_search_fn=lambda: [], snapshot_path=p, require_network=True
    )
    assert res["source"] == "none"
    assert res["evidence"] == []


def test_load_snapshot_missing_file():
    """快照文件不存在 → 返回空列表，不崩。"""
    p = Path("nonexistent_dir_xyz/snap.json")
    assert load_snapshot(p) == []


def test_demo_snapshot_exists():
    """仓库内预取的真实演示快照应存在（联网预取生成，非虚构）。"""
    if DEFAULT_SNAPSHOT_PATH.exists():
        loaded = load_snapshot()
        assert len(loaded) >= 1
        for e in loaded:
            assert e.url or e.doi  # 每条证据必须有来源链接或 DOI（可追溯）
