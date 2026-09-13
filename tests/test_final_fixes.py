"""终审修复：C1 /mcp 真实可用性、I1 空笔记残留、I2 env 误判、I3 vault 校验。

I4 空查询、I5 --top-k、I6 LIKE 转义、I8 toml 入口见各自测试文件。
"""

from pathlib import Path

import pytest

from ragdb.config import Settings
from ragdb.core import Core
from tests.helpers import make_vault


def test_mcp_endpoint_handshake(tmp_path: Path):
    """/mcp 必须真实可达：MCP initialize 握手返回 200 + session id。"""
    from fastapi.testclient import TestClient

    from ragdb.api.app import create_app

    settings = Settings.load(path=None).model_copy(
        update={"data_dir": tmp_path / "data", "vault_path": make_vault(tmp_path),
                "interval_secs": 0}
    )
    app = create_app(Core.from_settings(settings))
    # base_url 必须是本地地址：FastMCP 的 DNS rebinding 防护只放行 127.0.0.1/localhost
    with TestClient(app, base_url="http://127.0.0.1:8770") as tc:  # with 触发 lifespan
        resp = tc.post(
            "/mcp",
            json={"jsonrpc": "2.0", "method": "initialize",
                  "params": {"protocolVersion": "2025-03-26", "capabilities": {},
                             "clientInfo": {"name": "t", "version": "0"}},
                  "id": 1},
            headers={"Accept": "application/json, text/event-stream"},
        )
    assert resp.status_code == 200
    assert resp.headers.get("mcp-session-id")


def test_serve_lock_refuses_second_instance(tmp_path: Path):
    from fastapi.testclient import TestClient

    from ragdb.api.app import create_app

    settings = Settings.load(path=None).model_copy(
        update={"data_dir": tmp_path / "data", "vault_path": make_vault(tmp_path),
                "interval_secs": 0}
    )
    app1 = create_app(Core.from_settings(settings))
    with TestClient(app1):  # 第一个实例启动并持锁
        app2 = create_app(Core.from_settings(settings))
        with pytest.raises(RuntimeError, match="已被占用"), TestClient(app2):
            pass


def test_core_rejects_missing_vault(tmp_path: Path):
    settings = Settings.load(path=None).model_copy(
        update={"vault_path": tmp_path / "不存在"}
    )
    with pytest.raises(FileNotFoundError):
        Core.from_settings(settings)


def test_empty_note_removes_old_vectors(tmp_path: Path):
    from ragdb.ingest.chunker import Chunker
    from ragdb.ingest.connector import ObsidianConnector
    from ragdb.store.state import SyncState
    from ragdb.store.vector_store import VectorStore
    from ragdb.sync.engine import SyncEngine
    from tests.helpers import FakeEmbedder

    vault = make_vault(tmp_path / "vault")
    store = VectorStore(tmp_path / "db", dim=8)
    state = SyncState(tmp_path / "state.db")
    engine = SyncEngine(ObsidianConnector(vault), FakeEmbedder(dim=8), store,
                        state, Chunker(token_counter=len))
    engine.run()
    before = store.count()
    assert store.fetch_by_source("笔记2.md")
    (vault / "笔记2.md").write_text("", encoding="utf-8")  # 清空正文
    report = engine.run()
    assert report.updated == 1
    assert not store.fetch_by_source("笔记2.md")  # 旧向量被清
    assert store.count() < before


def test_toml_value_survives_unrelated_env(tmp_path: Path, monkeypatch):
    cfg = tmp_path / "ragdb.toml"
    cfg.write_text('device = "cpu"\n', encoding="utf-8")
    monkeypatch.setenv("DEVICE", "无论设什么都不该影响 ragdb")
    monkeypatch.setenv("PORT", "1")
    assert Settings.load(path=cfg).device == "cpu"
    assert Settings.load(path=cfg).port == 8770


def test_settings_load_discovers_cwd_toml(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("RAGDB_NO_CWD_CONFIG", raising=False)  # 本用例显式测发现特性
    monkeypatch.chdir(tmp_path)
    (tmp_path / "ragdb.toml").write_text("top_k = 7\n", encoding="utf-8")
    assert Settings.load(path=None).top_k == 7


def test_cli_config_flag_and_topk(tmp_path: Path, monkeypatch, capsys):
    from ragdb import cli

    cfg = tmp_path / "ragdb.toml"
    cfg.write_text("top_k = 7\n", encoding="utf-8")
    seen = {}

    class StubRetriever:
        def search(self, query, *, top_k=None, folder=None, tags=None):
            seen["top_k"] = top_k
            return []

    settings = Settings.load(path=cfg).model_copy(
        update={"data_dir": tmp_path / "d", "vault_path": make_vault(tmp_path)}
    )
    core = Core.from_settings(settings)
    stub = StubRetriever()
    core.__dict__["retriever"] = stub
    monkeypatch.setattr(cli, "_build_core", lambda *a, **kw: core)
    assert cli.main(["--config", str(cfg), "search", "词", "--top-k", "3"]) == 0
    assert seen["top_k"] == 3


def test_folder_like_escaping(tmp_path: Path):
    from ragdb.ingest.schema import Chunk
    from ragdb.store.vector_store import VectorStore

    store = VectorStore(tmp_path / "db", dim=8)
    import numpy as np
    v = np.zeros((1, 8), dtype="float32"); v[0][0] = 1
    store.upsert([Chunk("my_notes/a.md", "a", 0, "h", "内容", 2)],
                 np.tile(v, (1, 1)))
    store.upsert([Chunk("myXnotes/b.md", "b", 0, "h", "内容", 2)],
                 np.tile(v, (1, 1)))
    hits = store.search(v[0], k=10, folder="my_notes/")
    assert [h.source_id for h in hits] == ["my_notes/a.md"]


def test_empty_query_rejected(tmp_path: Path):
    from fastapi.testclient import TestClient

    from ragdb.api.app import create_app

    settings = Settings.load(path=None).model_copy(
        update={"data_dir": tmp_path / "data", "vault_path": make_vault(tmp_path),
                "interval_secs": 0}
    )
    app = create_app(Core.from_settings(settings))
    with TestClient(app) as tc:
        resp = tc.post("/api/v1/search", json={"query": "   "})
        assert resp.status_code == 422


def test_mcp_search_empty_query_message():
    from ragdb.mcp_server import _tool_search

    class StubRetriever:
        def search(self, *a, **kw):
            raise AssertionError("空查询不应触达检索")

    class StubCore:
        retriever = StubRetriever()

    assert "查询词" in _tool_search(StubCore(), "   ")


def test_folder_boundary_excludes_sibling_dirs(tmp_path: Path):
    """局部重审 I6 残留：folder="my_notes" 不得命中 my_notes2/。"""
    import numpy as np

    from ragdb.ingest.schema import Chunk
    from ragdb.store.vector_store import VectorStore

    store = VectorStore(tmp_path / "db", dim=8)
    v = np.zeros((1, 8), dtype="float32")
    v[0][0] = 1.0
    store.upsert([Chunk("my_notes/a.md", "a", 0, "h", "内容", 2)], np.tile(v, (1, 1)))
    store.upsert([Chunk("my_notes2/b.md", "b", 0, "h", "内容", 2)], np.tile(v, (1, 1)))
    store.upsert([Chunk("my_notes.md", "c", 0, "h", "内容", 2)], np.tile(v, (1, 1)))

    hits = store.search(v[0], k=10, folder="my_notes")   # 无尾斜杠
    assert sorted(h.source_id for h in hits) == ["my_notes.md", "my_notes/a.md"]
    hits2 = store.search(v[0], k=10, folder="my_notes/")
    assert sorted(h.source_id for h in hits2) == ["my_notes/a.md"]
