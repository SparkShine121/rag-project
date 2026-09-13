"""v1.2 端到端：obsidian + folder（md/代码/PDF 混合）+ github（mock PDF），fake 模型。"""

from pathlib import Path

import httpx

from ragdb.config import IngestConfig, Settings, SourceConfig
from ragdb.core import Core
from ragdb.ingest.connector import ObsidianConnector
from ragdb.ingest.folder import FolderConnector
from ragdb.ingest.github import GitHubConnector
from ragdb.ingest.multi import MultiSourceConnector
from tests.helpers import FakeEmbedder, FakeReranker, make_vault
from tests.test_pdf import make_pdf

DIM = 1024


def _folder_source(tmp_path: Path) -> SourceConfig:
    files = {
        "docs/说明.md": "# 项目说明\n\n这是一个混合类型知识源",
        "src/util.py": "def parse_args(argv):\n    return argv\n",
        "docs/报告.pdf": make_pdf(["报告第一页的关键数据", "报告第二页的结论"]),
    }
    for rel, content in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content) if isinstance(content, bytes) else \
            p.write_text(content, encoding="utf-8")
    return SourceConfig(name="local", type="folder", path=str(tmp_path))


def _github_connector(tmp_path: Path):
    tree = {"tree": [
        {"path": "README.md", "type": "blob", "sha": "shaR", "size": 5},
        {"path": "papers/论文.pdf", "type": "blob", "sha": "shaX", "size": 12},
    ], "truncated": False}
    routes = {("GET", "/git/trees/main"): (200, tree),
              ("GET", "/git/blobs/shaR"): (200, {
                  "content": __import__("base64").b64encode(b"repo readme").decode(),
                  "encoding": "base64", "size": 11}),
              ("GET", "/git/blobs/shaX"): (200, {
                  "content": __import__("base64").b64encode(make_pdf(["论文第一页"])).decode(),
                  "encoding": "base64", "size": 12})}
    def handler(req: httpx.Request) -> httpx.Response:
        for (m, suffix), (status, payload) in routes.items():
            if req.method == m and req.url.path.endswith(suffix):
                return httpx.Response(status, json=payload)
        return httpx.Response(404, json={})

    client = httpx.Client(transport=httpx.MockTransport(handler),
                          base_url="https://api.github.com")
    cfg = SourceConfig(name="gh", type="github", repo="o/r")
    ingest = IngestConfig(include_exts=[".md", ".pdf"])
    return cfg, GitHubConnector(cfg, client=client, ingest_cfg=ingest)


def _core(tmp_path: Path) -> Core:
    vault = make_vault(tmp_path / "vault")
    settings = Settings.load(path=None).model_copy(
        update={"vault_path": vault, "data_dir": tmp_path / "data",
                "interval_secs": 0}
    )
    core = Core.from_settings(settings)
    core.__dict__["embedder"] = FakeEmbedder(dim=DIM)
    core.__dict__["reranker"] = FakeReranker()
    obs = SourceConfig(name="obsidian", type="obsidian", path=str(vault))
    folder = _folder_source(tmp_path / "local")
    gh_cfg, gh_conn = _github_connector(tmp_path)
    core.__dict__["connector"] = MultiSourceConnector([
        (obs, ObsidianConnector(vault)),
        (folder, FolderConnector(folder, settings.ingest)),
        (gh_cfg, gh_conn),
    ])
    return core


def test_three_sources_mixed_types(tmp_path: Path):
    core = _core(tmp_path)
    report = core.engine.run()
    assert report.failed == []
    assert report.added == 6 + 3 + 2  # vault + folder(md/py/pdf) + github(md/pdf)
    ids = {n["source_id"] for n in core.store.list_notes()}
    assert any(i.startswith("obsidian/") for i in ids)
    assert any(i.startswith("local/") for i in ids)
    assert any(i.startswith("gh/") for i in ids)


def test_pdf_paginated_and_code_symbols_in_store(tmp_path: Path):
    core = _core(tmp_path)
    core.engine.run()
    pdf_headings = [h.heading_path
                    for h in core.store.fetch_by_source("local/docs/报告.pdf")]
    assert pdf_headings == ["报告.pdf > 第 1 页", "报告.pdf > 第 2 页"]
    code_headings = [h.heading_path
                     for h in core.store.fetch_by_source("local/src/util.py")]
    assert any("def parse_args" in h for h in code_headings)


def test_incremental_across_sources(tmp_path: Path):
    core = _core(tmp_path)
    core.engine.run()
    vault = Path(core.settings.sources[0].path) if core.settings.sources \
        else Path(core.settings.vault_path)
    # vault 内修改 → 仅 obsidian 源更新
    p = vault / "笔记1.md"
    p.write_text(p.read_text(encoding="utf-8") + "\n追加", encoding="utf-8")
    report = core.engine.run()
    assert report.updated == 1 and report.added == 0


def test_renamed_pdf_keeps_chunks(tmp_path: Path):
    """终审 C2：moved 分支必须走 pipeline——改名 PDF 不丢向量。"""
    core = _core(tmp_path)
    core.engine.run()
    before = core.store.fetch_by_source("local/docs/报告.pdf")
    assert len(before) == 2
    # 找到 folder 源根目录：从 connector items 取
    folder_root = next(conn._root for cfg, conn in core.connector._items
                       if cfg.name == "local")
    (folder_root / "docs" / "报告.pdf").rename(folder_root / "docs" / "报告v2.pdf")
    report = core.engine.run()
    assert report.moved == 1 and report.failed == []
    after = core.store.fetch_by_source("local/docs/报告v2.pdf")
    assert len(after) == 2  # 向量随移动保留（pipeline 分发正确）
    assert not core.store.fetch_by_source("local/docs/报告.pdf")
