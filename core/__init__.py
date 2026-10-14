"""核心数据结构与状态枚举。"""
from core.enums import (
    ClaimStatus,
    ClaimType,
    EvidenceSupport,
    IssueType,
    ReviewVerdict,
    RoleType,
)
from core.models import (
    Claim,
    Correction,
    DetectionReport,
    Evidence,
    ReviewResult,
    RoleJudgement,
    VerificationResult,
)

__all__ = [
    "Claim",
    "ClaimStatus",
    "ClaimType",
    "Correction",
    "DetectionReport",
    "Evidence",
    "EvidenceSupport",
    "IssueType",
    "ReviewResult",
    "ReviewVerdict",
    "RoleJudgement",
    "RoleType",
    "VerificationResult",
]
