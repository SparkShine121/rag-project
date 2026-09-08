"""测试辅助：fixture vault 构造与假模型（零网络、零模型下载）。"""

from __future__ import annotations

from pathlib import Path

from ragdb.ingest.connector import ObsidianConnector

_VAULT_NOTES: dict[str, str] = {
    "笔记1.md": "---\ntags: [RAG, 测试]\n---\n# 标题一\n这是第一篇笔记的正文内容，用于验证解析。\n",
    "笔记2.md": "# 标题二\n第二篇，将被删除测试用。\n",
    "笔记3.md": "# 标题三\n第三篇，将被移动测试用。\n",
    "短笔记.md": "短",
    "长笔记.md": (
        "# 长文\n引言部分。\n## 章节 A\n"
        + "甲" * 120
        + "\n### 小节 A1\n" + "乙" * 130
        + "\n## 章节 B\n" + "丙" * 150
        + "\n"
    ),
    "无标题.md": "没有标题的一篇笔记，只有一段普通文本内容。\n",
}


def make_vault(root: Path) -> Path:
    """创建 6 篇样例笔记 + 应被跳过的噪声文件（.obsidian/.trash/隐藏/非 md）。"""
    vault = root / "vault"
    for name, content in _VAULT_NOTES.items():
        p = vault / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    (vault / ".obsidian").mkdir()
    (vault / ".obsidian" / "config.json").write_text("{}", encoding="utf-8")
    (vault / ".trash").mkdir()
    (vault / ".trash" / "x.md").write_text("垃圾", encoding="utf-8")
    (vault / ".hidden.md").write_text("隐藏", encoding="utf-8")
    (vault / "attach.png").write_bytes(b"\x89PNG")
    return vault


def stamps(vault: Path) -> dict[str, tuple[float, int, str]]:
    """对 vault 现有 md 计算已知戳（mtime,size,hash），模拟已同步一轮的状态。"""
    return {
        doc.source_id: (doc.metadata["mtime"], len(doc.content), doc.content_hash)
        for doc in ObsidianConnector(vault).fetch_all()
    }
