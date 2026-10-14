"""外部文献检索模块：Crossref + OpenAlex（均为免费、无需 key 的公开 API）。

设计理由：
- 第一版只接这两个源，覆盖"DOI 精确核验"与"标题/关键词模糊匹配"两类最常见场景。
- 所有检索器返回统一的 List[Evidence]，失败不抛异常（返回空 + 记录原因），
  由分类器决定标记 UNVERIFIABLE 还是 INSUFFICIENT。
- 明确边界：只核验"元数据存在性 + 摘要层面支持关系"，不声称读取了全文。
"""
from retrieval.crossref import search_by_doi, search_bibliographic
from retrieval.openalex import search_by_title, search_by_keywords

__all__ = [
    "search_by_doi",
    "search_bibliographic",
    "search_by_title",
    "search_by_keywords",
]
