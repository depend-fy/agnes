"""VeriMind AI 核心数据结构（Python 3.9+ 兼容写法）。

阶段 2 补全：Evidence / VerificationResult / Correction / ReviewResult / DetectionReport。
所有"来源"字段必须带 URL + 检索时间；角色判断必须带 model_tag，区分真实多模型与单模型模拟。
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field

from core.enums import (
    ClaimStatus,
    ClaimType,
    EvidenceSupport,
    IssueType,
    ReviewVerdict,
    RoleType,
)


class Claim(BaseModel):
    """原子事实主张。

    - id: 唯一标识（如 "C001"）。
    - original_snippet: 原文片段，用于在报告里定位高亮。
    - normalized: 规范化后的主张表述。
    - type: 主张类型。
    - priority: 核验优先级（1 最高）。
    - status: 初步核验状态（默认 unverified）。
    """

    id: str = Field(..., min_length=1)
    original_snippet: str = Field(..., min_length=1)
    normalized: str
    type: ClaimType = ClaimType.GENERAL
    priority: int = 5
    status: ClaimStatus = ClaimStatus.UNVERIFIED


class Evidence(BaseModel):
    """外部证据。阶段 2 可为空列表；阶段 4 由 Crossref/OpenAlex 填充。"""

    id: str
    source_name: str                  # 如 "Crossref"
    url: str                          # 原始 URL（可点击）
    title: str
    authors: List[str] = Field(default_factory=list)
    year: Optional[int] = None
    doi: Optional[str] = None
    retrieved_at: datetime            # 检索时间（ISO）
    snippet: Optional[str] = None     # 摘要/片段；无全文不得声称读了全文
    supports: List[str] = Field(default_factory=list)  # 关联 claim ids
    support_level: EvidenceSupport = EvidenceSupport.PARTIAL_SUPPORT  # 对关联主张的支持度
    # 阶段 8 新增：证据来源等级（academic / wikipedia / web），供分类器保守化与 UI 分色
    source_tier: str = "academic"


class RoleJudgement(BaseModel):
    """单个角色对某主张的判断，记录分歧。"""

    role: RoleType
    judgement: str
    confidence_note: str              # 定性说明，不用伪精确概率
    model_tag: str                    # "single_model_simulated" 或真实模型名


class VerificationResult(BaseModel):
    """主张与证据的匹配及状态判定。"""

    claim_id: str
    status: ClaimStatus
    issue_types: List[IssueType] = Field(default_factory=list)
    rationale: str                    # 判断理由（可追溯）
    evidence_ids: List[str] = Field(default_factory=list)
    role_judgements: List[RoleJudgement] = Field(default_factory=list)


class Correction(BaseModel):
    """基于证据的修正记录。"""

    claim_id: str
    original_text: str
    suggested_text: str
    reason: str
    evidence_ids: List[str] = Field(default_factory=list)
    preserved_parts: List[str] = Field(default_factory=list)  # 保留的已支持部分


class ReviewResult(BaseModel):
    """独立复核结果。"""

    correction_id: Optional[str]
    verdict: ReviewVerdict
    passed: bool
    resolved_original_issue: bool
    introduced_new_errors: List[str] = Field(default_factory=list)
    new_unfounded_claims: List[str] = Field(default_factory=list)
    notes: str = ""


class DetectionReport(BaseModel):
    """完整检测报告（阶段 2 的端到端产物）。"""

    report_id: str
    input_text: str
    claims: List[Claim] = Field(default_factory=list)
    evidence: List[Evidence] = Field(default_factory=list)
    verification: List[VerificationResult] = Field(default_factory=list)
    corrections: List[Correction] = Field(default_factory=list)
    review: List[ReviewResult] = Field(default_factory=list)
    unresolved: List[str] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)
