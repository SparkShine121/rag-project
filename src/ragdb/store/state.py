"""同步状态库（SQLite）：文件戳、hash、chunk 计数与元信息。"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from ragdb.ingest.schema import FileStamp

_SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
    source_type TEXT NOT NULL DEFAULT 'obsidian',
    source_id   TEXT PRIMARY KEY,
    mtime       REAL NOT NULL,
    size        INTEGER NOT NULL,
    content_hash TEXT NOT NULL,
    chunk_count INTEGER NOT NULL,
    last_indexed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


class SyncState:
    def __init__(self, db_path: Path):
        self._db_path = db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            conn.executescript(_SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self._db_path)

    def get_all(self) -> dict[str, FileStamp]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT source_id, mtime, size, content_hash FROM files"
            ).fetchall()
        return {r[0]: (r[1], r[2], r[3]) for r in rows}

    def upsert(
        self, source_id: str, mtime: float, size: int,
        content_hash: str, chunk_count: int,
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO files (source_type, source_id, mtime, size,
                                       content_hash, chunk_count, last_indexed_at)
                   VALUES ('obsidian', ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(source_id) DO UPDATE SET
                       mtime=excluded.mtime, size=excluded.size,
                       content_hash=excluded.content_hash,
                       chunk_count=excluded.chunk_count,
                       last_indexed_at=excluded.last_indexed_at""",
                (source_id, mtime, size, content_hash, chunk_count,
                 datetime.now(UTC).isoformat()),
            )

    def delete(self, source_id: str) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM files WHERE source_id = ?", (source_id,))

    def get_meta(self, key: str, default: str | None = None) -> str | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT value FROM meta WHERE key = ?", (key,)
            ).fetchone()
        return row[0] if row else default

    def set_meta(self, key: str, value: str) -> None:
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO meta (key, value) VALUES (?, ?)
                   ON CONFLICT(key) DO UPDATE SET value=excluded.value""",
                (key, value),
            )
