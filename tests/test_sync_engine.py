from pathlib import Path

from ragdb.ingest.chunker import Chunker
from ragdb.ingest.connector import ObsidianConnector
from ragdb.store.state import SyncState
from ragdb.store.vector_store import VectorStore
from ragdb.sync.engine import SyncEngine
from tests.helpers import CountingEmbedder, FakeEmbedder, make_vault

DIM = 8


def _engine(vault: Path, tmp_path: Path, emb=None):
    emb = emb if emb is not None else FakeEmbedder(dim=DIM)
    store = VectorStore(tmp_path / "db", dim=DIM)
    state = SyncState(tmp_path / "state.db")
    engine = SyncEngine(
        ObsidianConnector(vault), emb, store, state, Chunker(token_counter=len)
    )
    return engine, emb, store, state


def test_initial_index(tmp_path: Path):
    vault = make_vault(tmp_path)
    engine, _, store, state = _engine(vault, tmp_path)
    report = engine.run()
    assert report.added == 6 and report.failed == []
    assert store.count() > 0
    assert len(state.get_all()) == 6
    assert report.duration > 0


def test_unchanged_no_reembed(tmp_path: Path):
    vault = make_vault(tmp_path)
    engine, emb, _, _ = _engine(vault, tmp_path, CountingEmbedder(FakeEmbedder(dim=DIM)))
    engine.run()
    calls_before = emb.calls
    report = engine.run()
    assert report.added == 0 and report.updated == 0
    assert emb.calls == calls_before  # 空扫描零嵌入


def test_move_does_not_reembed(tmp_path: Path):
    vault = make_vault(tmp_path)
    engine, emb, store, state = _engine(vault, tmp_path, CountingEmbedder(FakeEmbedder(dim=DIM)))
    engine.run()
    calls_before = emb.calls
    (vault / "笔记3.md").rename(vault / "moved.md")
    report = engine.run()
    assert report.moved == 1
    assert emb.calls == calls_before  # 移动零重嵌入
    assert store.fetch_by_source("moved.md")
    assert "笔记3.md" not in state.get_all()


def test_modify_reembeds(tmp_path: Path):
    vault = make_vault(tmp_path)
    engine, emb, _store, _ = _engine(vault, tmp_path, CountingEmbedder(FakeEmbedder(dim=DIM)))
    engine.run()
    calls_before = emb.calls
    p = vault / "笔记1.md"
    p.write_text(p.read_text(encoding="utf-8") + "\n追加内容", encoding="utf-8")
    report = engine.run()
    assert report.updated == 1 and emb.calls == calls_before + 1


def test_delete_cleans_store_and_state(tmp_path: Path):
    vault = make_vault(tmp_path)
    engine, _, store, state = _engine(vault, tmp_path)
    engine.run()
    before = store.count()
    (vault / "笔记2.md").unlink()
    report = engine.run()
    assert report.deleted == 1
    assert store.count() < before
    assert "笔记2.md" not in state.get_all()


def test_failure_isolation(tmp_path: Path):
    vault = make_vault(tmp_path)
    (vault / "bad.md").write_bytes(b"\xff\xfe\xff broken \x00")
    engine, _, _store, state = _engine(vault, tmp_path)
    report = engine.run()
    assert report.added == 6
    assert len(report.failed) == 1
    assert report.failed[0][0] == "bad.md"
    assert "bad.md" not in state.get_all()


def test_full_rebuild(tmp_path: Path):
    vault = make_vault(tmp_path)
    engine, _, store, state = _engine(vault, tmp_path)
    engine.run()
    (vault / "笔记2.md").unlink()
    engine.run()
    report = engine.run(full=True)
    assert report.added == 5
    assert len(state.get_all()) == 5 and store.count() > 0
