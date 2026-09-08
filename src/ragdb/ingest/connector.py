"""SourceConnector 抽象与 Obsidian 实现：vault 只读，增删改移识别。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from ragdb.ingest.schema import (
    ChangeSet,
    FileStamp,
    RawDocument,
)

_SKIP_DIRS = {".obsidian", ".trash"}


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
        text = p.read_text(encoding="utf-8")
        title = p.stem
        for line in text.splitlines():
            if line.startswith("# ") and not line.startswith("##"):
                title = line[2:].strip()
                break
        return RawDocument(
            source_type="obsidian",
            source_id=rel,
            title=title,
            content=text,
            metadata={"mtime": p.stat().st_mtime},
        )

    def fetch_all(self) -> list[RawDocument]:
        return [self._read(p) for p in self._walk()]

    def fetch_changes(self, known: dict[str, FileStamp]) -> ChangeSet:
        cs = ChangeSet()
        current: dict[str, tuple[float, int]] = {
            p.relative_to(self._vault).as_posix(): (
                p.stat().st_mtime,
                p.stat().st_size,
            )
            for p in self._walk()
        }
        deleted_ids = [r for r in known if r not in current]
        hash_to_old: dict[str, str] = {known[r][2]: r for r in deleted_ids}
        consumed: set[str] = set()

        for rel, (mtime, size) in current.items():
            k = known.get(rel)
            if k is not None and k[0] == mtime and k[1] == size:
                cs.unchanged += 1
                continue
            doc = self._read(self._vault / rel)
            if k is not None:
                if doc.content_hash == k[2]:
                    cs.unchanged += 1  # 内容没变，引擎稍后刷新戳
                else:
                    cs.modified.append(doc)
            elif doc.content_hash in hash_to_old and hash_to_old[doc.content_hash] not in consumed:
                old_id = hash_to_old[doc.content_hash]
                consumed.add(old_id)
                cs.moved.append((old_id, doc))
            else:
                cs.added.append(doc)

        cs.deleted = [r for r in deleted_ids if r not in consumed]
        return cs
