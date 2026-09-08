from ragdb.retrieve.aggregator import aggregate
from ragdb.store.vector_store import Hit


def _hit(sid: str, idx: int, content: str, tags=None, dense=0.5) -> Hit:
    return Hit(
        source_id=sid, title=sid.removesuffix(".md"), chunk_index=idx,
        heading_path=f"{sid} > H", content=content, tags=tags or [],
        score_dense=dense,
    )


class FakeStore:
    def __init__(self, notes: dict[str, list[str]]):
        self.notes = notes

    def fetch_by_source(self, sid: str) -> list[Hit]:
        return [_hit(sid, i, c) for i, c in enumerate(self.notes.get(sid, []))]


def _len(t: str) -> int:
    return len(t)


def test_dedupe_and_order():
    ranked = [(_hit("a.md", 0, "甲"), 0.9), (_hit("a.md", 1, "乙"), 0.8),
              (_hit("b.md", 0, "丙"), 0.7)]
    results = aggregate(ranked, store=FakeStore({"a.md": ["甲", "乙"], "b.md": ["丙"]}),
                        token_counter=_len)
    assert [r.source_id for r in results] == ["a.md", "b.md"]
    assert results[0].score_rerank == 0.9 and results[0].whole_note is True


def test_short_note_returns_whole():
    ranked = [(_hit("a.md", 0, "甲"), 0.9)]
    results = aggregate(ranked, store=FakeStore({"a.md": ["第一段", "第二段"]}),
                        token_counter=_len, short_note_tokens=600)
    assert results[0].whole_note is True
    assert results[0].snippets == ["第一段\n\n第二段"]


def test_neighbor_expansion_for_long_note():
    chunks = ["字" * 700, "核心命中内容", "字" * 700]  # 全笔记 >600 → 不整篇
    ranked = [(_hit("a.md", 1, chunks[1]), 0.9)]
    results = aggregate(ranked, store=FakeStore({"a.md": chunks}),
                        token_counter=_len)
    assert results[0].whole_note is False
    assert "核心命中内容" in results[0].snippets[0]
    assert results[0].snippets[0].count("字" * 700) == 2  # 相邻两块被扩展进来


def test_budget_trims_low_score_groups():
    ranked = [(_hit("a.md", 0, "甲" * 20), 0.9), (_hit("b.md", 0, "乙" * 20), 0.8)]
    results = aggregate(ranked, store=FakeStore({"a.md": ["甲" * 20], "b.md": ["乙" * 20]}),
                        token_counter=_len, budget=15)
    assert len(results) == 1  # b 组剩余预算为 0 被裁掉
    assert len(results[0].snippets[0]) <= 15  # a 组自身被截断


def test_empty_ranked():
    assert aggregate([], store=FakeStore({}), token_counter=_len) == []
