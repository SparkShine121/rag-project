from pathlib import Path

from ragdb.config import Settings
from ragdb.core import Core
from ragdb.retrieve.retriever import Retriever
from ragdb.store.vector_store import Hit
from tests.helpers import FakeEmbedder

DIM = 8


def _hit(sid: str, content: str) -> Hit:
    return Hit(source_id=sid, title=sid, chunk_index=0,
               heading_path=f"{sid} > H", content=content, tags=["X"])


class RecordingStore:
    def __init__(self, hits):
        self.hits = hits
        self.calls = []

    def search(self, vector, k, *, source_type=None, folder=None, tags=None):
        self.calls.append({"vector": vector, "k": k, "folder": folder, "tags": tags})
        return self.hits

    def fetch_by_source(self, sid):
        return [h for h in self.hits if h.source_id == sid]


class ScoredReranker:
    def __init__(self):
        self.calls = []

    def rerank(self, query, docs):
        self.calls.append((query, docs))
        table = {"h2": 0.9, "h3": 0.6, "h1": 0.3}
        return [table.get(d[:2], 0.0) for d in docs]


def test_retriever_pipeline(tmp_path: Path):
    hits = [_hit("h1", "h1内容"), _hit("h2", "h2内容"), _hit("h3", "h3内容")]
    store = RecordingStore(hits)
    emb = FakeEmbedder(dim=DIM)
    rr = ScoredReranker()
    retriever = Retriever(emb, rr, store, token_counter=len,
                          recall_k=20, top_k=2, token_budget=3000,
                          short_note_tokens=600)

    results = retriever.search("查询", folder="目录/", tags=["X"])

    assert store.calls[0]["k"] == 20 and store.calls[0]["folder"] == "目录/"
    assert store.calls[0]["tags"] == ["X"]
    assert (store.calls[0]["vector"] == emb.embed_query("查询")).all()
    assert rr.calls[0][0] == "查询"
    assert [d[:2] for d in rr.calls[0][1]] == ["h1", "h2", "h3"]
    assert [r.source_id for r in results] == ["h2", "h3"]  # 重排分降序取 top_k


def test_retriever_empty_store(tmp_path: Path):
    store = RecordingStore([])
    retriever = Retriever(FakeEmbedder(dim=DIM), ScoredReranker(), store,
                          token_counter=len)
    assert retriever.search("啥都没有") == []


def test_retriever_top_k_override(tmp_path: Path):
    hits = [_hit("h1", "h1内容"), _hit("h2", "h2内容")]
    store = RecordingStore(hits)
    retriever = Retriever(FakeEmbedder(dim=DIM), ScoredReranker(), store,
                          token_counter=len, top_k=5)
    results = retriever.search("查询", top_k=1)
    assert len(results) == 1 and results[0].source_id == "h2"


def test_core_lazy_and_cached(tmp_path: Path):
    settings = Settings.load(path=None).model_copy(
        update={"data_dir": tmp_path, "vault_path": tmp_path}
    )
    core = Core.from_settings(settings)
    assert core.store is core.store
    assert core.state is core.state
    assert core.connector is core.connector
    assert core.chunker is core.chunker
    assert core.engine is core.engine
    assert core.retriever is core.retriever
    # 真实 BGEM3 懒加载不触发下载（未访问 .model）
    assert core.hub.embedder.dim == 1024
    assert isinstance(core.retriever, Retriever)
