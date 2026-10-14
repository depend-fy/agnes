"""独立复核模块：检查修正结果是否引入新问题。

设计理由：
- 对每条 Correction 独立复核，关注：是否解决原问题、是否引入新事实错误、
  是否有新的无依据结论、证据与修改后主张是否匹配。
- 无 LLM（stub）时走确定性桩：检查 suggested_text 是否为空 / 是否弱化了原主张。
- 结果写入 ReviewResult（passed + 失败原因 + 新错误清单）。
"""
from review.reviewer import review_corrections

__all__ = ["review_corrections"]
