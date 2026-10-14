"""基于证据的修正模块。

设计理由：
- 只对有证据支撑的问题主张（INSUFFICIENT/PARTIAL/CONTRADICTED）生成修正建议。
- UNVERIFIABLE（查无证据）不强行修，避免编造证据（符合阶段 0 原则）。
- 修正必须关联证据 ID；保留原文中已支持的部分，只改有证据的内容。
- live 模式由 LLM 生成；无 key 走桩（桩返回占位并明确标注"模拟/需人工"）。
"""
from correction.generator import generate_corrections

__all__ = ["generate_corrections"]
