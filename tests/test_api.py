"""API 层测试：TestClient + 假组件注入（零模型）。"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ragdb.api.app import create_app
from ragdb.config import Settings
from ragdb.core import Core
from ragdb.retrieve.schema import SearchResult
from ragdb.sync.engine import SyncReport


class FakeRetriever:
    def __init__(self):
        self.calls = []

    def search(self, query, *, top_k=None, folder=None, tags=None):
        self.calls.append({"query": query, "top_k": top_k, "folder": folder,
                           "tags": tags})
        return [SearchResult(
            source_id="a.md", title="a", heading_path="a > H",
            snippets=["片段"], whole_note=True, score_rerank=0.9,
            score_dense=0.5, tags=["RAG"],
        )]


class FakeEngine:
    def __init__(self):
        self.calls = []

    def run(self, full: bool = False) -> SyncReport:
        self.calls.append(full)
        return SyncReport(added=1 if not full else 6)


@pytest.fixture()
def client(tmp_path: Path):
    settings = Settings.load(path=None).model_copy(
        update={"data_dir": tmp_path / "data", "vault_path": tmp_path / "vault",
                "interval_secs": 0}  # 测试不起后台同步循环
    )
    core = Core.from_settings(settings)
    retriever = FakeRetriever()
    engine = FakeEngine()
    core.__dict__["retriever"] = retriever  # 预置 cached_property
    core.__dict__["engine"] = engine
    app = create_app(core)
    return TestClient(app), core, retriever, engine


def test_search_endpoint(client):
    tc, _, retriever, _ = client
    resp = tc.post("/api/v1/search",
                   json={"query": "测试查询", "top_k": 3, "folder": "目录/"})
    assert resp.status_code == 200
    body = resp.json()
    assert body[0]["source_id"] == "a.md" and body[0]["whole_note"] is True
    assert retriever.calls[0] == {"query": "测试查询", "top_k": 3,
                                  "folder": "目录/", "tags": None}


def test_search_invalid_body(client):
    tc, *_ = client
    resp = tc.post("/api/v1/search", json={"folder": "x"})  # 缺 query
    assert resp.status_code == 422
    assert "error" in resp.json()


def test_notes_list_and_detail(client):
    tc, core, *_ = client
    import numpy as np

    from ragdb.ingest.schema import Chunk
    chunks = [Chunk("n1.md", "n1", 0, "n1 > H", "全文内容", 4, ["T1"])]
    core.store.upsert(chunks, np.zeros((1, 1024), dtype="float32"))
    listing = tc.get("/api/v1/notes").json()
    assert listing == [{"source_id": "n1.md", "title": "n1", "tags": ["T1"]}]
    detail = tc.get("/api/v1/notes/n1.md")
    assert detail.status_code == 200
    assert detail.json()["content"] == "全文内容"
    missing = tc.get("/api/v1/notes/nope.md")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "not_found"


def test_sync_endpoint(client):
    tc, _, _, engine = client
    resp = tc.post("/api/v1/sync", json={"full": False})
    assert resp.status_code == 200
    assert resp.json()["added"] == 1
    assert engine.calls == [False]
    resp = tc.post("/api/v1/sync", json={"full": True})
    assert resp.json()["added"] == 6 and engine.calls == [False, True]


def test_health_endpoint(client):
    tc, *_ = client
    resp = tc.get("/api/v1/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok" and body["db_ok"] is True
    assert body["note_count"] == 0 and body["models_loaded"] is False


def test_mcp_route_mounted(client):
    tc, *_ = client
    app = tc.app
    assert any(getattr(r, "path", "") == "/mcp" for r in app.routes)
