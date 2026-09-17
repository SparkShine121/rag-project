"""MCP 工具函数与服务器构建测试（stub core，零模型）。"""

import asyncio

from ragdb.core import InflightTracker
from ragdb.mcp_server import (
    _tool_get_note,
    _tool_list_notes,
    _tool_search,
    build_mcp,
)
from ragdb.retrieve.schema import SearchResult
from ragdb.store.vector_store import Hit


class StubRetriever:
    def __init__(self, results):
        self.results = results
        self.calls = []

    def search(self, query, *, top_k=None, folder=None, tags=None):
        self.calls.append({"query": query, "top_k": top_k, "folder": folder,
                           "tags": tags})
        return self.results


class StubStore:
    def __init__(self, notes):
        self.notes = notes  # dict[sid -> list[Hit]]

    def fetch_by_source(self, sid):
        return self.notes.get(sid, [])

    def list_notes(self, *, folder=None, tag=None):
        out = []
        for sid in sorted(self.notes):
            if folder and not sid.startswith(folder):
                continue
            hits = self.notes[sid]
            if tag and tag not in hits[0].tags:
                continue
            out.append({"source_id": sid, "title": hits[0].title,
                        "tags": hits[0].tags})
        return out


class StubCore:
    def __init__(self, retriever, store):
        self.retriever = retriever
        self.store = store
        self.search_inflight = InflightTracker()  # v1.3.2：_tool_search 计数契约


def _result(sid) -> SearchResult:
    return SearchResult(source_id=sid, title=sid, heading_path=f"{sid} > 标题",
                        snippets=["命中片段内容"], whole_note=True,
                        score_rerank=0.87, score_dense=0.5, tags=["RAG"])


def _hit(sid, content, tags=None) -> Hit:
    return Hit(source_id=sid, title=sid, chunk_index=0,
               heading_path=f"{sid} > H", content=content,
               tags=tags or ["RAG"])


def test_tool_search_formats_results():
    core = StubCore(StubRetriever([_result("笔记1.md")]), StubStore({}))
    out = _tool_search(core, "查询", top_k=3)
    assert "笔记1.md" in out and "笔记1.md > 标题" in out
    assert "0.870" in out and "命中片段内容" in out and "整篇" in out


def test_tool_search_params_passthrough_and_empty():
    retriever = StubRetriever([])
    core = StubCore(retriever, StubStore({}))
    assert _tool_search(core, "查询", top_k=2, folder="目录/", tags=["X"]) == "未找到相关内容。"
    assert retriever.calls[0] == {"query": "查询", "top_k": 2,
                                  "folder": "目录/", "tags": ["X"]}


def test_tool_get_note():
    core = StubCore(None, StubStore({"n.md": [_hit("n.md", "第一段"), _hit("n.md", "第二段")]}))
    out = _tool_get_note(core, "n.md")
    assert "第一段" in out and "第二段" in out and "tags: RAG" in out
    assert _tool_get_note(core, "ghost.md") == "未找到笔记: ghost.md"


def test_tool_list_notes():
    core = StubCore(None, StubStore({
        "b.md": [_hit("b.md", "x", tags=["T2"])],
        "a.md": [_hit("a.md", "y", tags=["T1"])],
    }))
    out = _tool_list_notes(core)
    assert out.splitlines()[0].startswith("a.md | a.md | tags: T1")
    assert "b.md" in out


def test_build_mcp_registers_three_tools():
    core = StubCore(StubRetriever([]), StubStore({}))
    mcp = build_mcp(core)
    tools = asyncio.run(mcp.list_tools())
    assert sorted(t.name for t in tools) == ["get_note", "list_notes", "search"]
