"""CLI 路由、锁协调与端到端集成测试（零模型）。"""

import json
from pathlib import Path

import httpx
import pytest

from ragdb import cli
from ragdb.config import Settings
from ragdb.core import Core
from tests.helpers import FakeEmbedder, FakeReranker, make_vault

DIM = 1024


# ---------- 路由 ----------

@pytest.mark.parametrize("argv,cmd", [
    (["serve"], "_cmd_serve"), (["sync"], "_cmd_sync"),
    (["rebuild"], "_cmd_rebuild"), (["status"], "_cmd_status"),
])
def test_routing(monkeypatch, argv, cmd):
    calls = []
    monkeypatch.setattr(cli, cmd, lambda core: calls.append(cmd) or 0)
    assert cli.main(argv) == 0
    assert calls == [cmd]


def test_search_command_prints(monkeypatch, capsys):
    from ragdb.retrieve.schema import SearchResult

    class StubRetriever:
        def search(self, query, **kw):
            assert query == "测试词"
            return [SearchResult(source_id="a.md", title="a", heading_path="a > H",
                                 snippets=["片段"], whole_note=True,
                                 score_rerank=0.9, tags=[])]

    monkeypatch.setattr(cli, "_build_core",
                        lambda *a, **kw: _stub_core(retriever=StubRetriever()))
    assert cli.main(["search", "测试词"]) == 0
    assert "a.md" in capsys.readouterr().out


def _stub_core(tmp_path: Path | None = None, **overrides):
    settings = Settings.load(path=None).model_copy(
        update={"data_dir": (tmp_path or Path("/tmp")) / "d", "interval_secs": 0}
    )
    core = Core.from_settings(settings)
    core.__dict__.update(overrides)
    return core


# ---------- 锁协调 ----------

class StubEngine:
    def __init__(self):
        self.calls = []

    def run(self, full=False):
        self.calls.append(full)
        return {"added": 1}


class OkResp:
    status_code = 200

    def json(self):
        return {"added": 9}


def test_sync_delegates_to_running_serve(monkeypatch, tmp_path):
    core = _stub_core(tmp_path, engine=StubEngine())
    monkeypatch.setattr(cli.httpx, "get",
                        lambda *a, **kw: OkResp())
    posted = {}
    monkeypatch.setattr(cli.httpx, "post",
                        lambda url, json=None, timeout=None: posted.update(
                            {"url": url, "json": json}) or OkResp())
    assert cli._coordinated_sync(core, full=True) == 0
    assert posted["url"].endswith("/api/v1/sync") and posted["json"] == {"full": True}
    assert core.engine.calls == []  # 本进程未写


def test_sync_falls_back_to_lock(monkeypatch, tmp_path):
    core = _stub_core(tmp_path, engine=StubEngine())
    monkeypatch.setattr(cli.httpx, "get",
                        lambda *a, **kw: (_ for _ in ()).throw(httpx.ConnectError("down")))
    assert cli._coordinated_sync(core, full=False) == 0
    assert core.engine.calls == [False]


def test_lock_blocked_when_held(monkeypatch, tmp_path):
    import fcntl

    core = _stub_core(tmp_path, engine=StubEngine())
    monkeypatch.setattr(cli.httpx, "get",
                        lambda *a, **kw: (_ for _ in ()).throw(httpx.ConnectError("down")))
    core.settings.data_dir.mkdir(parents=True, exist_ok=True)
    with open(core.settings.data_dir / "ragdb.lock", "w") as held:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert cli._coordinated_sync(core, full=False) == 1
    assert core.engine.calls == []


# ---------- 端到端（fake 全链路） ----------

def test_end_to_end(tmp_path):
    vault = make_vault(tmp_path / "vault")
    settings = Settings.load(path=None).model_copy(
        update={"vault_path": vault, "data_dir": tmp_path / "data",
                "interval_secs": 0}
    )
    core = Core.from_settings(settings)
    core.__dict__["embedder"] = FakeEmbedder(dim=DIM)
    core.__dict__["reranker"] = FakeReranker()

    report = core.engine.run()
    assert report.added == 6 and report.failed == []

    results = core.retriever.search("标题一")
    assert 0 < len(results) <= core.settings.top_k
    assert results[0].source_id and results[0].snippets
    assert isinstance(results[0].whole_note, bool)

    p = vault / "笔记1.md"
    p.write_text(p.read_text(encoding="utf-8") + "\n追加", encoding="utf-8")
    assert core.engine.run().updated == 1
    assert any(n["source_id"] == "obsidian/笔记1.md" for n in core.store.list_notes())

    before = core.store.count()
    (vault / "笔记3.md").rename(vault / "moved.md")
    assert core.engine.run().moved == 1
    assert core.store.count() == before  # 移动无增减
    assert not core.store.fetch_by_source("obsidian/笔记3.md")  # 无孤儿


def test_sync_local_path_prints_json(monkeypatch, tmp_path, capsys):
    """冒烟发现：CLI 本地写路径把 SyncReport 数据类直接 json.dumps 会炸。"""
    from ragdb.sync.engine import SyncReport

    class RealReportEngine:
        def run(self, full=False):
            return SyncReport(added=3)

    core = _stub_core(tmp_path, engine=RealReportEngine())
    monkeypatch.setattr(cli.httpx, "get",
                        lambda *a, **kw: (_ for _ in ()).throw(httpx.ConnectError("down")))
    assert cli._coordinated_sync(core, full=False) == 0
    out = capsys.readouterr().out
    assert json.loads(out)["added"] == 3


def test_sync_exit_code_nonzero_when_failed(monkeypatch, tmp_path, capsys):
    from ragdb.sync.engine import SyncReport

    class FailedEngine:
        def run(self, full=False):
            return SyncReport(added=1, failed=[("gh", "限流")])

    core = _stub_core(tmp_path, engine=FailedEngine())
    monkeypatch.setattr(cli.httpx, "get",
                        lambda *a, **kw: (_ for _ in ()).throw(httpx.ConnectError("down")))
    assert cli._coordinated_sync(core, full=False) == 1
    assert "限流" in capsys.readouterr().out
