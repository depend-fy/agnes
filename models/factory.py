"""LLM Provider 工厂：根据 Settings 构建可用 provider 列表。

设计理由：
- 三角色各自绑定独立 provider（事实审查员→Agnes，证据审查员/独立复核员→DeepSeek）。
- 若某 provider 无 key 或 mode=stub，对应角色自动降级为 RuleStub，
  并在 report.metadata 里标注哪些角色是桩、哪些是真实调用。
- 成本控制：统计各 provider 的 calls_made，供 pipeline 在超预算时提前中止。
"""
from __future__ import annotations

from typing import Dict, List

from core.config import Settings, get_settings
from core.enums import RoleType
from models.base import LLMProvider, LLMResponse
from models.openai_compat import OpenAICompatClient
from models.rule_stub import RuleStubProvider


def build_providers(settings: Settings | None = None) -> Dict[RoleType, LLMProvider]:
    """按角色返回 {RoleType: provider} 映射。"""
    settings = settings or get_settings()
    use_stub = settings.mode == "stub"

    def _pick(endpoint, role_label: str) -> LLMProvider:
        if endpoint is not None and not use_stub and endpoint.has_key:
            return OpenAICompatClient(
                name=endpoint.name,
                base_url=endpoint.base_url,
                api_key=endpoint.api_key,
                model=endpoint.model,
                timeout_s=endpoint.timeout_s,
            )
        return RuleStubProvider(name=f"{role_label}_stub", model_tag="stub")

    return {
        RoleType.FACT_REVIEWER: _pick(settings.agnes, "fact_reviewer"),
        RoleType.EVIDENCE_REVIEWER: _pick(settings.deepseek, "evidence_reviewer"),
        RoleType.INDEPENDENT_REVIEWER: _pick(settings.deepseek, "independent_reviewer"),
    }


def provider_summary(providers: Dict[RoleType, LLMProvider]) -> Dict[str, str]:
    """返回 {角色名: model_tag}，写入 report.metadata 供报告区分真实/桩。"""
    return {role.value: p.model_tag for role, p in providers.items()}
