"""SourceConnector 抽象与 Obsidian 实现：vault 只读，增删改移识别。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

import frontmatter

from ragdb.ingest.changeset import build_change_set
from ragdb.ingest.schema import (
    ChangeSet,
    FileStamp,
    RawDocument,
)

_SKIP_DIRS = {".obsidian", ".trash"}


def extract_title(content: str, stem: str) -> str:
    """首个 H1 作标题（跳过 frontmatter），无则用文件名 stem。md 系连接器共用。"""
    body = frontmatter.loads(content).content
    for line in body.splitlines():
        if line.startswith("# ") and not line.startswith("##"):
            return line[2:].strip()
    return stem


class SourceConnector(ABC):
    """数据源抽象。v2 渠道（聊天记录/数据文件/代码仓库/微信读书）按此接口接入。"""

    @abstractmethod
    def fetch_all(self) -> list[RawDocument]: ...

    @abstractmethod
    def fetch_changes(self, known: dict[str, FileStamp]) -> ChangeSet: ...


class ObsidianConnector(SourceConnector):
    def __init__(self, vault_path: Path):
        self._vault = vault_path

    def _walk(self) -> list[Path]:
        out: list[Path] = []
        for p in sorted(self._vault.rglob("*.md")):
            rel = p.relative_to(self._vault)
            if any(part.startswith(".") or part in _SKIP_DIRS for part in rel.parts):
                continue
            out.append(p)
        return out

    def _read(self, p: Path) -> RawDocument:
        rel = p.relative_to(self._vault).as_posix()
        st = p.stat()
        try:
            text = p.read_text(encoding="utf-8")
            read_error = False
        except UnicodeDecodeError:
            text = p.read_bytes().decode("utf-8", errors="replace")
            read_error = True
        title = extract_title(text, p.stem)
        return RawDocument(
            source_type="obsidian",
            source_id=rel,
            title=title,
            content=text,
            metadata={
                "mtime": st.st_mtime, "size": st.st_size, "read_error": read_error
            },
        )

    def fetch_all(self) -> list[RawDocument]:
        return [self._read(p) for p in self._walk()]

    def fetch_changes(self, known: dict[str, FileStamp]) -> ChangeSet:
        files = {p.relative_to(self._vault).as_posix(): p for p in self._walk()}
        current: dict[str, FileStamp] = {}
        for rel, p in files.items():
            st = p.stat()
            k = known.get(rel)
            if k is not None and k[0] == st.st_mtime and k[1] == st.st_size:
                current[rel] = (st.st_mtime, st.st_size, k[2])  # 快路径：沿用旧 hash
            else:
                current[rel] = (st.st_mtime, st.st_size, self._read(p).content_hash)
        return build_change_set(known, current, lambda rel: self._read(self._vault / rel))
