"""阶段 1 自检：核心数据结构可用。

运行（在 verimind 目录下）：
    python -m pytest -q
"""
from core.models import Claim, ClaimStatus, ClaimType


def test_claim_defaults():
    c = Claim(id="C001", original_snippet="片段", normalized="主张", type=ClaimType.NUMERIC)
    assert c.status == ClaimStatus.UNVERIFIED
    assert c.priority == 5


def test_claim_roundtrip():
    c = Claim(id="C002", original_snippet="s", normalized="n")
    data = c.model_dump()
    c2 = Claim.model_validate(data)
    assert c2 == c
