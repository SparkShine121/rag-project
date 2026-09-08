"""small-to-big 聚合：块是检索单位，笔记是返回单位。"""

from __future__ import annotations

from collections.abc import Callable

from ragdb.retrieve.schema import SearchResult
from ragdb.store.vector_store import Hit

TokenCounter = Callable[[str], int]


def aggregate(
    ranked: list[tuple[Hit, float]], *, store,
    token_counter: TokenCounter, budget: int = 3000,
    short_note_tokens: int = 600,
) -> list[SearchResult]:
    """ranked：重排后降序的 (Hit, 分数)；按笔记去重保序，整篇/邻块扩展，预算裁剪。"""
    results: list[SearchResult] = []
    used = 0
    seen: set[str] = set()

    for hit, score in ranked:
        if hit.source_id in seen:
            continue
        seen.add(hit.source_id)

        chunks = store.fetch_by_source(hit.source_id)
        full_tokens = sum(token_counter(c.content) for c in chunks)
        if full_tokens < short_note_tokens:
            content = "\n\n".join(c.content for c in chunks)
            snippets, whole = [content], True
        else:
            by_idx = {c.chunk_index: c.content for c in chunks}
            idxs = sorted(
                i for i in (hit.chunk_index - 1, hit.chunk_index, hit.chunk_index + 1)
                if i in by_idx
            )
            content = "\n\n".join(by_idx[i] for i in idxs)
            snippets, whole = [content], False

        remaining = budget - used
        if remaining <= 0:
            break
        tok = token_counter(content)
        if tok > remaining:
            content = content[:remaining]  # 字符近似截断（handoff：budget 按 token 计的工程近似）
            tok = token_counter(content)
            if not content:
                break
            snippets = [content]

        used += tok
        results.append(
            SearchResult(
                source_id=hit.source_id, title=hit.title,
                heading_path=hit.heading_path, snippets=snippets,
                whole_note=whole, score_rerank=score,
                score_dense=hit.score_dense, tags=list(hit.tags),
            )
        )
    return results
