from pathlib import Path

import numpy as np
import pytest

from ragdb.ingest.schema import Chunk
from ragdb.store.vector_store import VectorStore

DIM = 8


def _chunk(source_id: str, idx: int, content: str = "内容", tags=None) -> Chunk:
    return Chunk(
        source_id=source_id, title=source_id.removesuffix(".md"), chunk_index=idx,
        heading_path=f"{source_id} > H", content=content, token_count=len(content),
        tags=tags or [],
    )


def _unit(dim: int, hot: int) -> np.ndarray:
    v = np.zeros(dim, dtype="float32")
    v[hot] = 1.0
    return v


@pytest.fixture()
def store(tmp_path: Path) -> VectorStore:
    return VectorStore(tmp_path / "lancedb", dim=DIM)


def test_upsert_count_and_overwrite(store: VectorStore):
    a0, a1 = _chunk("a.md", 0), _chunk("a.md", 1)
    b0 = _chunk("b.md", 0)
    store.upsert([a0, a1], np.stack([_unit(DIM, 0), _unit(DIM, 1)]))
    store.upsert([b0], _unit(DIM, 2)[None, :])
    assert store.count() == 3
    # 覆盖 upsert：a.md 旧行全删再写
    store.upsert([a0], _unit(DIM, 3)[None, :])
    assert store.count() == 2
    hits = store.fetch_by_source("a.md")
    assert len(hits) == 1 and hits[0].vector[3] == pytest.approx(1.0)


def test_delete_by_source(store: VectorStore):
    store.upsert([_chunk("a.md", 0)], _unit(DIM, 0)[None, :])
    store.upsert([_chunk("b.md", 0)], _unit(DIM, 1)[None, :])
    store.delete_by_source("a.md")
    assert store.count() == 1
    store.delete_by_source("a.md")  # 幂等
    assert store.count() == 1


def test_fetch_by_source_sorted(store: VectorStore):
    chunks = [_chunk("a.md", 2), _chunk("a.md", 0), _chunk("a.md", 1)]
    vecs = np.stack([_unit(DIM, i) for i in (2, 0, 1)])
    store.upsert(chunks, vecs)
    hits = store.fetch_by_source("a.md")
    assert [h.chunk_index for h in hits] == [0, 1, 2]
    assert all(h.vector is not None for h in hits)


def test_search_nearest_with_score(store: VectorStore):
    store.upsert([_chunk("a.md", 0, "甲"), _chunk("b.md", 0, "乙")],
                 np.stack([_unit(DIM, 0), _unit(DIM, 1)]))
    hits = store.search(_unit(DIM, 1), k=1)
    assert len(hits) == 1
    assert hits[0].source_id == "b.md"
    assert 0 < hits[0].score_dense <= 1.0


def test_search_filters(store: VectorStore):
    store.upsert(
        [_chunk("目录/甲.md", 0, tags=["RAG"]), _chunk("目录/乙.md", 0, tags=["其它"]),
         _chunk("根.md", 0)],
        np.stack([_unit(DIM, 0)] * 3),
    )
    by_type = store.search(_unit(DIM, 0), k=10, source_type="obsidian")
    assert len(by_type) == 3
    by_folder = store.search(_unit(DIM, 0), k=10, folder="目录/")
    assert {h.source_id for h in by_folder} == {"目录/甲.md", "目录/乙.md"}
    by_tags = store.search(_unit(DIM, 0), k=10, tags=["RAG"])
    assert [h.source_id for h in by_tags] == ["目录/甲.md"]
    none_type = store.search(_unit(DIM, 0), k=10, source_type="chat")
    assert none_type == []


def test_search_empty_store(store: VectorStore):
    assert store.search(_unit(DIM, 0), k=5) == []
    assert store.count() == 0


def test_list_notes_dedup_and_filters(store: VectorStore):
    store.upsert([_chunk("目录/甲.md", 0, tags=["RAG"]),
                  _chunk("目录/甲.md", 1, tags=["RAG"]),
                  _chunk("根.md", 0, tags=["其它"])],
                 np.stack([_unit(DIM, 0)] * 3))
    all_notes = store.list_notes()
    assert {n["source_id"] for n in all_notes} == {"目录/甲.md", "根.md"}
    assert [n["source_id"] for n in all_notes] == sorted(
        {"目录/甲.md", "根.md"}
    )  # 升序稳定（注意 Unicode 序：根 < 目）
    assert store.list_notes(folder="目录/")[0]["source_id"] == "目录/甲.md"
    assert store.list_notes(tag="其它")[0]["source_id"] == "根.md"
    assert store.list_notes(tag="不存在") == []
