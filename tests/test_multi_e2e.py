"""双源端到端：obsidian（真实目录遍历）+ 模拟 GitHub 源，fake 模型全链路。"""

from pathlib import Path

from ragdb.config import Settings, SourceConfig
from ragdb.core import Core
from ragdb.ingest.changeset import build_change_set
from ragdb.ingest.connector import ObsidianConnector
from ragdb.ingest.multi import MultiSourceConnector
from ragdb.ingest.schema import RawDocument, content_hash
from tests.helpers import FakeEmbedder, FakeReranker, make_vault

DIM = 1024

GH_DOCS = {
    "docs/设计.md": "# 设计文档\n\n系统的总体设计与取舍",
    "README.md": "# 仓库说明\n\n这是模拟的 GitHub 仓库入口文档",
}


class FakeGitHubSource:
    """模拟 github 子连接器：预设文档、内容 hash 驱动增量。"""

    def __init__(self, docs: dict[str, str]):
        self.docs = dict(docs)

    def _doc(self, p: str) -> RawDocument:
        return RawDocument(source_type="github", source_id=p,
                           title=Path(p).stem, content=self.docs[p], metadata={})

    def fetch_all(self) -> list[RawDocument]:
        return [self._doc(p) for p in self.docs]

    def fetch_changes(self, known) :
        current = {p: (0.0, len(c), content_hash(c)) for p, c in self.docs.items()}
        return build_change_set(known, current, self._doc)


def _core(tmp_path: Path, gh_docs: dict[str, str] | None):
    vault = make_vault(tmp_path / "vault")
    settings = Settings.load(path=None).model_copy(
        update={"vault_path": vault, "data_dir": tmp_path / "data",
                "interval_secs": 0}
    )
    core = Core.from_settings(settings)
    core.__dict__["embedder"] = FakeEmbedder(dim=DIM)
    core.__dict__["reranker"] = FakeReranker()
    obs_cfg = SourceConfig(name="obsidian", type="obsidian", path=str(vault))
    items: list = [(obs_cfg, ObsidianConnector(vault))]
    if gh_docs is not None:
        items.append((SourceConfig(name="gh", type="github", repo="o/r"),
                      FakeGitHubSource(gh_docs)))
    core.__dict__["connector"] = MultiSourceConnector(items)
    return core


def test_dual_source_initial_index_and_prefixes(tmp_path: Path):
    core = _core(tmp_path, GH_DOCS)
    report = core.engine.run()
    assert report.added == 6 + len(GH_DOCS) and report.failed == []
    ids = {n["source_id"] for n in core.store.list_notes()}
    assert any(i.startswith("obsidian/") for i in ids)
    assert {"gh/docs/设计.md", "gh/README.md"} <= ids


def test_search_returns_prefixed_ids(tmp_path: Path):
    core = _core(tmp_path, GH_DOCS)
    core.engine.run()
    results = core.retriever.search("设计文档")
    assert results and all("/" in r.source_id for r in results)


def test_github_source_removal_cleans_orphans(tmp_path: Path):
    core = _core(tmp_path, GH_DOCS)
    core.engine.run()
    before_obsidian = sum(1 for n in core.store.list_notes()
                          if n["source_id"].startswith("obsidian/"))
    # gh 源从配置移除 → 下轮同步整体清理
    core = _core(tmp_path, gh_docs=None)
    core.__dict__["embedder"] = FakeEmbedder(dim=DIM)
    core.__dict__["reranker"] = FakeReranker()
    report = core.engine.run()
    assert report.deleted == len(GH_DOCS)
    ids = {n["source_id"] for n in core.store.list_notes()}
    assert not any(i.startswith("gh/") for i in ids)
    assert sum(1 for i in ids if i.startswith("obsidian/")) == before_obsidian


def test_github_source_update_only_touches_that_source(tmp_path: Path):
    core = _core(tmp_path, GH_DOCS)
    core.engine.run()
    docs = dict(GH_DOCS)
    docs["docs/设计.md"] = "# 设计文档 v2\n\n内容已更新"
    core = _core(tmp_path, docs)
    core.__dict__["embedder"] = FakeEmbedder(dim=DIM)
    core.__dict__["reranker"] = FakeReranker()
    report = core.engine.run()
    assert report.updated == 1 and report.added == 0
    assert "gh/docs/设计.md" in {n["source_id"] for n in core.store.list_notes()}


def test_rebuild_idempotent(tmp_path: Path):
    core = _core(tmp_path, GH_DOCS)
    core.engine.run()
    report = core.engine.run(full=True)
    assert report.added == 6 + len(GH_DOCS)
    assert core.engine.run().added == 0  # 再跑一轮全量后无变更
