import os
from pathlib import Path

from ragdb.ingest.connector import ObsidianConnector
from tests.helpers import make_vault, stamps


def test_fetch_all_skips_noise(tmp_path: Path):
    vault = make_vault(tmp_path)
    docs = ObsidianConnector(vault).fetch_all()
    ids = {d.source_id for d in docs}
    assert len(ids) == 6
    assert not any(
        i.startswith((".obsidian", ".trash")) or "/." in f"/{i}" for i in ids
    )


def test_change_detect_add_modify_delete(tmp_path: Path):
    vault = make_vault(tmp_path)
    conn = ObsidianConnector(vault)
    known = stamps(vault)
    (vault / "新笔记.md").write_text("# 新\n内容", encoding="utf-8")
    p = vault / "笔记1.md"
    p.write_text(p.read_text(encoding="utf-8") + "\n追加", encoding="utf-8")
    (vault / "笔记2.md").unlink()
    cs = conn.fetch_changes(known)
    assert [d.source_id for d in cs.added] == ["新笔记.md"]
    assert cs.modified and cs.modified[0].source_id == "笔记1.md"
    assert cs.deleted == ["笔记2.md"]


def test_move_detected_without_readd(tmp_path: Path):
    vault = make_vault(tmp_path)
    conn = ObsidianConnector(vault)
    known = stamps(vault)
    (vault / "子目录").mkdir()
    (vault / "笔记3.md").rename(vault / "子目录" / "笔记3.md")
    cs = conn.fetch_changes(known)
    assert len(cs.moved) == 1
    old_id, doc = cs.moved[0]
    assert old_id == "笔记3.md" and doc.source_id == "子目录/笔记3.md"
    assert not cs.added and "笔记3.md" not in cs.deleted


def test_same_hash_still_unchanged(tmp_path: Path):
    vault = make_vault(tmp_path)
    conn = ObsidianConnector(vault)
    known = stamps(vault)
    os.utime(vault / "笔记1.md", (0, 0))  # 只动 mtime 不动内容
    cs = conn.fetch_changes(known)
    assert not cs.modified and not cs.added


def test_title_ignores_frontmatter_heading(tmp_path: Path):
    vault = make_vault(tmp_path)
    (vault / "fm_title.md").write_text(
        "---\n# YAML注释行不是标题\ntags: [X]\n---\n# 真标题\n正文", encoding="utf-8"
    )
    docs = {d.source_id: d for d in ObsidianConnector(vault).fetch_all()}
    assert docs["fm_title.md"].title == "真标题"
