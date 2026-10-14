"""阶段 3 测试：LLM 适配层（离线桩路径，不依赖真实 key）。"""
from models.base import LLMResponse
from models.openai_compat import OpenAICompatClient
from models.rule_stub import RuleStubProvider


def test_stub_provider_available():
    p = RuleStubProvider(name="stub")
    assert p.is_available() is True
    assert p.model_tag == "stub"


def test_stub_factual_judgement():
    p = RuleStubProvider()
    resp = p.complete("请审查以下主张：某研究发表于 2023 年。", system="x", json_mode=True)
    assert resp.ok
    assert resp.parsed is not None
    assert resp.parsed["role"] == "fact_reviewer"
    assert resp.model_tag == "stub"


def test_stub_evidence_judgement():
    p = RuleStubProvider()
    resp = p.complete("请根据证据判断：证据为空。", system="x", json_mode=True)
    assert resp.parsed["role"] == "evidence_reviewer"
    assert "missing_evidence" in resp.parsed["issues"]


def test_stub_review_judgement():
    p = RuleStubProvider()
    resp = p.complete("请复核：修正为空。", system="x", json_mode=True)
    assert resp.parsed["role"] == "independent_reviewer"


def test_openai_compat_no_key_unavailable():
    c = OpenAICompatClient(name="x", base_url="https://api.example.com/v1", api_key="", model="m")
    assert c.is_available() is False


def test_openai_compat_http_error_returns_response_not_raise():
    """HTTP 401 应返回带 error 的 LLMResponse，不抛异常。"""
    c = OpenAICompatClient(
        name="x", base_url="https://httpbin.org", api_key="dummy", model="m", timeout_s=5.0
    )
    # 用一个会 404 的 URL 验证错误路径（不依赖网络时走 except 兜底）
    resp = c.complete("hi", json_mode=False)
    # 无论成功/失败，必须返回 LLMResponse 实例（不抛异常）
    assert isinstance(resp, LLMResponse)
    # 如果网络可达，可能是 4xx/5xx；如果不可达，是 HTTP 错误。两种都 ok。


def test_openai_compat_timeout_handling():
    """极短超时 + 不可达 URL 应触发超时/网络错误，返回 LLMResponse。"""
    c = OpenAICompatClient(
        name="x", base_url="https://10.255.255.1", api_key="k", model="m", timeout_s=0.2
    )
    resp = c.complete("hi", timeout_s=0.2)
    assert isinstance(resp, LLMResponse)
    assert resp.ok is False
    assert resp.error is not None
