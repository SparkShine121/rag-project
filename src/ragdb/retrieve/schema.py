"""检索结果结构。"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SearchResult:
    source_id: str
    title: str
    heading_path: str
    snippets: list[str] = field(default_factory=list)
    whole_note: bool = False
    score_rerank: float = 0.0
    score_dense: float = 0.0
    tags: list[str] = field(default_factory=list)
