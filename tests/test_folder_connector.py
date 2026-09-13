"""FolderConnector 测试：白名单遍历、排除目录、大小/数量上限、二进制 hash。"""

import hashlib
from pathlib import Path

from ragdb.config import IngestConfig, Settings, SourceConfig
from ragdb.ingest.folder import FolderConnector
from tests.test_pdf import make_pdf


def _mk(tmp_path: Path, files: dict, **kw) -> tuple[FolderConnector, SourceConfig]:
    for rel, content in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content) if isinstance(content, bytes) else \
            p.write_text(content, encoding="utf-8")
    cfg = SourceConfig(name="local", type="folder", path=str(tmp_path), **kw)
    # 走真实合并链路：Settings.effective_ingest(cfg) 应用来源级覆盖
    settings = Settings(
        sources=[cfg],
        ingest=IngestConfig(include_exts=[".md", ".py", ".pdf"],
                            exclude_dirs=[".git", "node_modules"]),
    )
    return FolderConnector(cfg, ingest_cfg=settings.effective_ingest(cfg)), cfg


def test_walk_respects_whitelist_and_excludes(tmp_path: Path):
    conn, _ = _mk(tmp_path, {
        "a.md": "# A\n内容", "b.py": "x = 1\n",
        "c.pdf": make_pdf(["页内容"]), "d.exe": b"MZbinary",
        "node_modules/e.md": "# 排除", ".hidden.md": "隐藏",
    })
    ids = {d.source_id for d in conn.fetch_all()}
    assert {"a.md", "b.py", "c.pdf"} <= ids
    assert not any("node_modules" in i or i.startswith(".") or
                   i.endswith(".exe") for i in ids)


def test_pdf_doc_carries_binary_and_hash(tmp_path: Path):
    data = make_pdf(["页内容"])
    conn, _ = _mk(tmp_path, {"c.pdf": data})
    doc = conn.fetch_all()[0]
    assert doc.binary == data and doc.content == ""
    assert doc.content_hash == hashlib.sha256(data).hexdigest()


def test_oversized_file_reported_not_silent(tmp_path: Path):
    big = "x" * (2 * 1024 * 1024)
    conn, _ = _mk(tmp_path, {"big.md": big}, max_file_mb=1)
    cs = conn.fetch_changes({})
    assert not cs.added
    assert any("超过大小上限" in reason for _, reason in cs.failed)


def test_max_files_cap_hint(tmp_path: Path):
    files = {f"f{i}.md": f"内容 {i}" for i in range(5)}
    conn, _ = _mk(tmp_path, files, max_files_per_source=3)
    cs = conn.fetch_changes({})
    assert len(cs.added) == 3
    assert any("达到文件数上限" in reason for _, reason in cs.failed)


def test_incremental_modify_and_delete(tmp_path: Path):
    files = {"a.md": "第一版"}
    conn, _cfg = _mk(tmp_path, files)
    cs = conn.fetch_changes({})
    assert len(cs.added) == 1
    h = cs.added[0].content_hash
    cs2 = conn.fetch_changes({"a.md": (0.0, 9, h)})
    assert cs2.unchanged == 1
    (tmp_path / "a.md").write_text("第二版", encoding="utf-8")
    cs3 = conn.fetch_changes({"a.md": (0.0, 9, h)})
    assert len(cs3.modified) == 1
    (tmp_path / "a.md").unlink()
    cs4 = conn.fetch_changes({"a.md": (0.0, 9, cs3.modified[0].content_hash)})
    assert cs4.deleted == ["a.md"]


def test_factory_builds_folder_connector(tmp_path):
    from ragdb.config import Settings
    from ragdb.ingest.factory import build_connectors

    cfg = SourceConfig(name="local", type="folder", path=str(tmp_path))
    items = build_connectors(Settings(sources=[cfg]))
    assert items[0][1].__class__.__name__ == "FolderConnector"
