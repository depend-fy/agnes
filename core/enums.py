"""核心枚举：核验状态 / 主张类型 / 问题类型 / 角色 / 证据支持度 / 复核结论。

独立成文件避免循环依赖；Pydantic 模型只需 import 这些枚举。
"""
from enum import Enum


class ClaimStatus(str, Enum):
    """核验状态（六态）。"""

    UNVERIFIED = "unverified"
    VERIFIED = "verified"
    CONTRADICTED = "contradicted"
    PARTIAL = "partial"
    INSUFFICIENT = "insufficient"
    UNVERIFIABLE = "unverifiable"
    CONFLICTING_SOURCES = "conflicting_sources"


class ClaimType(str, Enum):
    """主张类型：用于路由到不同检测/检索策略。"""

    EXISTENCE = "existence"
    METADATA = "metadata"
    CAUSAL = "causal"
    NUMERIC = "numeric"
    TIME_PERSON_ORG = "time_person_org"
    LOGIC = "logic"
    GENERAL = "general"


class IssueType(str, Enum):
    """问题类型（八类），可一条主张命中多类。"""

    FACT_ERROR = "fact_error"
    CITATION_NOT_EXIST = "citation_not_exist"
    METADATA_MISMATCH = "metadata_mismatch"
    CITATION_CONCLUSION_MISMATCH = "citation_conclusion_mismatch"
    NUMERIC_ERROR = "numeric_error"
    TIME_PERSON_ORG_ERROR = "time_person_org_error"
    OVERREACH_LOGIC = "overreach_logic"
    MISSING_EVIDENCE = "missing_evidence"
    SOURCE_CONFLICT = "source_conflict"


class RoleType(str, Enum):
    FACT_REVIEWER = "fact_reviewer"
    EVIDENCE_REVIEWER = "evidence_reviewer"
    INDEPENDENT_REVIEWER = "independent_reviewer"


class EvidenceSupport(str, Enum):
    """证据对主张的支持程度（用于证据-主张匹配）。"""

    DIRECT_SUPPORT = "direct_support"
    PARTIAL_SUPPORT = "partial_support"
    REFUTES = "refutes"
    IRRELEVANT = "irrelevant"


class ReviewVerdict(str, Enum):
    """独立复核结论。"""

    PASS = "pass"
    FAIL = "fail"
