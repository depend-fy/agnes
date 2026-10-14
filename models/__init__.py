"""LLM 适配层：统一接口 + OpenAI 兼容实现 + 离线桩 + 工厂。

设计理由：
- LLMProvider 抽象把"调用模型"与"角色逻辑"解耦，换 provider 不改角色。
- OpenAICompatClient 通过 httpx 调任意 OpenAI 兼容端点（DeepSeek / Agnes 都适用）。
- RuleStub 在无 key / live 模式关闭时提供确定性输出，保证离线闭环可跑。
- 每次调用产出 LLMResponse（含耗时、token、成本估计、model_tag、错误信息），
  供 pipeline 汇总到 report.metadata，支持成本控制与可追溯。
"""
