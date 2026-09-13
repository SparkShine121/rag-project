"""folder 来源连接器：本地目录按白名单收多类型文件（md/pdf/代码）。"""

from __future__ import annotations

from pathlib import Path

from ragdb.config import IngestConfig, SourceConfig
from ragdb.ingest.changeset import build_change_set
from ragdb.ingest.connector import SourceConnector, read_md
from ragdb.ingest.schema import ChangeSet, FileStamp, RawDocument


class FolderConnector(SourceConnector):
    def __init__(self, source: SourceConfig, ingest_cfg: IngestConfig):
        self._cfg = source
        self._root = Path(source.path).expanduser()
        self._ingest = ingest_cfg
        self._skipped: list[tuple[str, str]] = []

    def _walk(self) -> list[Path]:
        exts = {e.lower() for e in self._ingest.include_exts}
        excl = set(self._ingest.exclude_dirs)
        max_bytes = self._ingest.max_file_mb * 1024 * 1024
        limit = self._ingest.max_files_per_source
        out: list[Path] = []
        skipped: list[tuple[str, str]] = []
        count = 0
        for p in sorted(self._root.rglob("*")):
            if not p.is_file():
                continue
            rel = p.relative_to(self._root)
            if any(part.startswith(".") or part in excl for part in rel.parts):
                continue
            if p.suffix.lower() not in exts:
                continue  # 白名单外直接忽略（不计入数量上限）
            size = p.stat().st_size
            rel_posix = rel.as_posix()
            if size > max_bytes:
                skipped.append((rel_posix,
                                f"超过大小上限（{self._ingest.max_file_mb}MB）"))
                continue
            if count >= limit:
                skipped.append((rel_posix,
                                f"达到文件数上限（{limit}）——其余文件未索引"))
                continue
            count += 1
            out.append(p)
        self._skipped = skipped
        return out

    def _read(self, p: Path) -> RawDocument:
        rel = p.relative_to(self._root).as_posix()
        if p.suffix.lower() == ".pdf":
            data = p.read_bytes()
            return RawDocument(
                source_type="folder", source_id=rel, title=p.stem,
                content="",
                metadata={"mtime": p.stat().st_mtime, "size": p.stat().st_size},
                binary=data,
            )
        return read_md(p, rel, "folder")

    def fetch_all(self) -> list[RawDocument]:
        return [self._read(p) for p in self._walk()]

    def fetch_changes(self, known: dict[str, FileStamp]) -> ChangeSet:
        files = {p.relative_to(self._root).as_posix(): p for p in self._walk()}
        current: dict[str, FileStamp] = {}
        for rel, p in files.items():
            st = p.stat()
            k = known.get(rel)
            if k is not None and k[0] == st.st_mtime and k[1] == st.st_size:
                current[rel] = (st.st_mtime, st.st_size, k[2])  # 快路径沿用旧 hash
            else:
                current[rel] = (st.st_mtime, st.st_size, self._read(p).content_hash)
        cs = build_change_set(known, current,
                              lambda rel: self._read(self._root / rel))
        cs.failed.extend(self._skipped)
        return cs
