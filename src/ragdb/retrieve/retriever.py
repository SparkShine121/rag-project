"""检索编排：嵌入 → 向量召回 → 重排 → 聚合。"""

from __future__ import annotations

from collections.abc import Callable

from ragdb.retrieve.aggregator import aggregate
from ragdb.retrieve.schema import SearchResult
from ragdb.store.vector_store import Hit

TokenCounter = Callable[[str], int]


class Retriever:
    def __init__(
        self, embedder, reranker, store, token_counter: TokenCounter, *,
        recall_k: int = 20, top_k: int = 5, rerank_top_k: int = 10,
        token_budget: int = 3000, short_note_tokens: int = 600,
    ):
        self._embedder = embedder
        self._reranker = reranker
        self._store = store
        self._counter = token_counter
        self._recall_k = recall_k
        self._top_k = top_k
        self._rerank_top_k = rerank_top_k
        self._budget = token_budget
        self._short = short_note_tokens

    def search(
        self, query: str, *, top_k: int | None = None,
        folder: str | None = None, tags: list[str] | None = None,
    ) -> list[SearchResult]:
        k = top_k if top_k is not None else self._top_k
        vector = self._embedder.embed_query(query)
        hits: list[Hit] = self._store.search(
            vector, self._recall_k, folder=folder, tags=tags
        )
        if not hits:
            return []
        # 交叉编码昂贵（M4 实测约 100ms/对）：只对稠密分前 rerank_top_k 精排
        candidates = hits[: self._rerank_top_k]
        scores = self._reranker.rerank(query, [h.content for h in candidates])
        ranked = sorted(
            zip(candidates, scores, strict=True), key=lambda p: p[1], reverse=True
        )[:k]
        return aggregate(
            ranked, store=self._store, token_counter=self._counter,
            budget=self._budget, short_note_tokens=self._short,
        )
