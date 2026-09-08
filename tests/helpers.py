"""测试辅助：fixture vault 构造与假模型（零网络、零模型下载）。"""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np

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
    """对 vault 现有 md 计算已知戳（mtime,st_size,hash），模拟已同步一轮的状态。
    size 语义必须与 connector 的 stat().st_size 一致（字节数，非字符数）。"""
    conn = ObsidianConnector(vault)
    out: dict[str, tuple[float, int, str]] = {}
    for doc in conn.fetch_all():
        st = (vault / doc.source_id).stat()
        out[doc.source_id] = (st.st_mtime, st.st_size, doc.content_hash)
    return out


class FakeEmbedder:
    """确定性哈希嵌入：同文同向量、异文异向量、已 L2 归一化。"""

    def __init__(self, dim: int = 8, seed: int = 0):
        self.dim = dim
        self._seed = seed

    def _vec(self, text: str) -> np.ndarray:
        digest = hashlib.blake2b(
            f"{self._seed}:{text}".encode(), digest_size=64
        ).digest()
        raw = np.frombuffer(digest, dtype=np.uint8).astype("float32")
        v = np.tile(raw, self.dim // len(raw) + 1)[: self.dim]
        return v / np.linalg.norm(v)

    def embed(self, texts: list[str]) -> np.ndarray:
        return np.stack([self._vec(t) for t in texts])

    def embed_query(self, query: str) -> np.ndarray:
        return self._vec(query)


class FakeReranker:
    """字符重叠打分：query 与 doc 的字符集合 Jaccard。"""

    def rerank(self, query: str, docs: list[str]) -> list[float]:
        q = set(query)
        return [
            len(q & set(d)) / max(len(q | set(d)), 1) for d in docs
        ]


class CountingEmbedder:
    """包装 Embedder 并统计 embed() 调用次数（验证移动不重嵌入）。"""

    def __init__(self, inner):
        self.inner = inner
        self.dim = inner.dim
        self.calls = 0

    def embed(self, texts: list[str]) -> np.ndarray:
        self.calls += 1
        return self.inner.embed(texts)

    def embed_query(self, query: str) -> np.ndarray:
        return self.inner.embed_query(query)
