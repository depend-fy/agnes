"""角色模块：三个独立检测角色的提示词封装与结构化调用。

设计理由：
- 每个角色绑定独立 provider + 模型 + 提示词，通过 LLMProvider 抽象调用。
- 角色之间通过结构化 JSON（RoleJudgement）交换结果，不共享上下文。
- 角色层不直接依赖具体 provider 实现，只依赖 LLMProvider 接口。
"""
