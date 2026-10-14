"""OpenAI 兼容 LLM 客户端（httpx 实现）。

适用于任意 OpenAI 兼容端点（DeepSeek / Agnes / 其他）。
设计理由：
- 用 httpx 而非 openai 官方 SDK，避免额外依赖，且对非 OpenAI 厂商同样适用。
- 结构化输出：json_mode=True 时加 response_format={"type":"json_object"}（如 provider 支持）。
- 解析失败不抛异常：把原始文本 + 错误信息塞进 LLMResponse，由上层决定降级。
"""
from __future__ import annotations

import json
import time
from typing import Any, Dict, Optional

import httpx

from models.base import LLMProvider, LLMResponse


class OpenAICompatClient(LLMProvider):
    """OpenAI 兼容 Chat Completions 客户端。"""

    def __init__(
        self,
        name: str,
        base_url: str,
        api_key: str,
        model: str,
        timeout_s: float = 60.0,
    ) -> None:
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.model_tag = model          # 记录真实模型名，供报告区分
        self.timeout_s = timeout_s
        self.calls_made = 0
        # 阶段 7：成本/延迟统计真实入账（累计 token/耗时，供 metrics 汇总）
        self.total_tokens_in = 0
        self.total_tokens_out = 0
        self.total_latency_s = 0.0
        self.last_responses: list[LLMResponse] = []

    def is_available(self) -> bool:
        return bool(self.api_key)

    def complete(
        self,
        prompt: str,
        system: str = "",
        json_mode: bool = False,
        timeout_s: Optional[float] = None,
    ) -> LLMResponse:
        timeout = timeout_s or self.timeout_s
        url = f"{self.base_url}/chat/completions"
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system or "You are a helpful assistant."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        self.calls_made += 1
        start = time.time()
        try:
            with httpx.Client(timeout=timeout) as client:
                resp = client.post(
                    url,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
            latency = time.time() - start
            if resp.status_code != 200:
                return LLMResponse(
                    raw_text=resp.text[:500],
                    model_tag=self.model_tag,
                    provider=self.name,
                    latency_s=latency,
                    error=f"HTTP {resp.status_code}: {resp.text[:200]}",
                )
            data = resp.json()
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            usage = data.get("usage", {})
            parsed: Optional[Dict[str, Any]] = None
            parse_error: Optional[str] = None
            if json_mode:
                try:
                    parsed = json.loads(content)
                except (json.JSONDecodeError, ValueError) as e:
                    parse_error = f"JSON 解析失败: {e}"
            resp_obj = LLMResponse(
                raw_text=content,
                parsed=parsed,
                model_tag=self.model_tag,
                provider=self.name,
                latency_s=latency,
                tokens_in=usage.get("prompt_tokens", 0),
                tokens_out=usage.get("completion_tokens", 0),
                error=parse_error,
            )
            self._accumulate(resp_obj)
            return resp_obj
        except httpx.TimeoutException:
            resp_obj = LLMResponse(
                model_tag=self.model_tag,
                provider=self.name,
                latency_s=time.time() - start,
                error=f"超时（>{timeout}s）",
            )
            self._accumulate(resp_obj)
            return resp_obj
        except httpx.HTTPError as e:
            resp_obj = LLMResponse(
                model_tag=self.model_tag,
                provider=self.name,
                latency_s=time.time() - start,
                error=f"HTTP 错误: {e}",
            )
            self._accumulate(resp_obj)
            return resp_obj
        except Exception as e:  # noqa: BLE001 - 兜底，保证不抛到上层
            resp_obj = LLMResponse(
                model_tag=self.model_tag,
                provider=self.name,
                latency_s=time.time() - start,
                error=f"未知错误: {e}",
            )
            self._accumulate(resp_obj)
            return resp_obj

    def _accumulate(self, r: LLMResponse) -> None:
        """阶段 7：把单次调用的 token/耗时累计到 provider，供成本统计。"""
        self.total_tokens_in += r.tokens_in
        self.total_tokens_out += r.tokens_out
        self.total_latency_s += r.latency_s
        self.last_responses.append(r)
