"""阶段 3 测试：角色层（离线桩 provider 下）。"""
from core.enums import RoleType
from core.models import Claim
from roles import fact_reviewer, evidence_reviewer, independent_reviewer, orchestrator
from models.rule_stub import RuleStubProvider


def _claim() -> Claim:
    return Claim(id="C001", original_snippet="s", normalized="某研究发表于 2023 年")


def test_fact_reviewer_stub():
    p = RuleStubProvider()
    js = fact_reviewer.run(p, [_claim()], "某研究发表于 2023 年。")
    assert len(js) == 1
    assert js[0].role == RoleType.FACT_REVIEWER
    assert js[0].model_tag == "stub"


def test_evidence_reviewer_stub():
    p = RuleStubProvider()
    js = evidence_reviewer.run(p, [_claim()], [], "某研究发表于 2023 年。")
    assert len(js) == 1
    assert js[0].role == RoleType.EVIDENCE_REVIEWER


def test_independent_reviewer_stub():
    p = RuleStubProvider()
    js = independent_reviewer.run(p, [_claim()], [], [], [], "某研究发表于 2023 年。")
    assert len(js) == 1
    assert js[0].role == RoleType.INDEPENDENT_REVIEWER


def test_orchestrator_returns_all_roles():
    providers = {
        RoleType.FACT_REVIEWER: RuleStubProvider(),
        RoleType.EVIDENCE_REVIEWER: RuleStubProvider(),
        RoleType.INDEPENDENT_REVIEWER: RuleStubProvider(),
    }
    result = orchestrator.run_all_roles(providers, [_claim()], [], "某研究发表于 2023 年。")
    js = result["judgements"]
    assert len(js) == 3  # 每角色 1 条 × 3 角色
    assert "fact_reviewer" in result["metadata"]["model_tags"]
    assert "evidence_reviewer" in result["metadata"]["model_tags"]
    assert "independent_reviewer" in result["metadata"]["model_tags"]


def test_orchestrator_llm_calls_recorded():
    providers = {
        RoleType.FACT_REVIEWER: RuleStubProvider(),
        RoleType.EVIDENCE_REVIEWER: RuleStubProvider(),
        RoleType.INDEPENDENT_REVIEWER: RuleStubProvider(),
    }
    result = orchestrator.run_all_roles(providers, [_claim()], [], "x")
    calls = result["metadata"]["llm_calls"]
    assert len(calls) == 3
    assert all(c["model_tag"] == "stub" for c in calls)
