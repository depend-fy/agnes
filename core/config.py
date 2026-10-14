"""配置加载：从 .env 读取运行模式 / 模型端点 / 成本控制。

阶段 3：Settings 直接由 from_env 构造，agnes/deepseek 为 LLMEndpoint。
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


def _load_env() -> None:
    """加载项目根目录的 .env（若存在）。"""
    root = Path(__file__).resolve().parent.parent
    load_dotenv(root / ".env")


_load_env()


@dataclass
class LLMEndpoint:
    """单个 LLM 端点（OpenAI 兼容协议）。"""

    name: str
    base_url: str
    api_key: str
    model: str
    timeout_s: int = 60
    max_calls: int = 30

    @property
    def has_key(self) -> bool:
        return bool(self.api_key)


@dataclass
class Settings:
    mode: str = "stub"            # stub | live
    agnes: LLMEndpoint | None = None
    deepseek: LLMEndpoint | None = None
    crossref_mailto: str = ""
    enable_web_search: bool = True  # 阶段 8：是否启用非学术（Wikipedia + 网页）检索入口

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            mode=os.getenv("VERIMIND_MODE", "stub"),
            agnes=LLMEndpoint(
                name="agnes",
                base_url=os.getenv("VERIMIND_AGNESES_BASE_URL", "https://api.agnes-ai.cn/v1"),
                api_key=os.getenv("VERIMIND_AGNESES_API_KEY", ""),
                model=os.getenv("VERIMIND_AGNESES_MODEL", "agnes-3.0-flash"),
                timeout_s=int(os.getenv("VERIMIND_LLM_TIMEOUT", "60")),
            ),
            deepseek=LLMEndpoint(
                name="deepseek",
                base_url=os.getenv("VERIMIND_DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
                api_key=os.getenv("VERIMIND_DEEPSEEK_API_KEY", ""),
                model=os.getenv("VERIMIND_DEEPSEEK_MODEL", "deepseek-v4.1-flash"),
                timeout_s=int(os.getenv("VERIMIND_LLM_TIMEOUT", "60")),
            ),
            crossref_mailto=os.getenv("VERIMIND_CROSSREF_MAILTO", ""),
            enable_web_search=os.getenv("VERIMIND_ENABLE_WEB_SEARCH", "true").lower() not in ("0", "false", "no"),
        )


def get_settings() -> Settings:
    return Settings.from_env()


def validate_live_settings(s: Settings | None = None) -> list[str]:
    """校验 live 模式所需配置，返回缺失/问题清单（供 UI 清晰报错）。

    规则：
    - mode=live 时，Agnes 与 DeepSeek 都需有 API key，否则对应角色降级为桩。
    - 返回问题描述列表；空列表 = 配置完整。
    """
    s = s or get_settings()
    problems: list[str] = []
    if s.mode != "live":
        return []
    if s.agnes is None or not s.agnes.has_key:
        problems.append("VERIMIND_AGNESES_API_KEY 未配置（事实审查员将降级为离线桩）")
    if s.deepseek is None or not s.deepseek.has_key:
        problems.append("VERIMIND_DEEPSEEK_API_KEY 未配置（证据/复核角色将降级为离线桩）")
    return problems
