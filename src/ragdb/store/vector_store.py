"""LanceDB 向量库：向量 + 血缘元数据同表。单写者由外部保证，读侧并发安全。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import lancedb
import numpy as np
import pyarrow as pa

from ragdb.ingest.schema import Chunk


def _esc(s: str) -> str:
    return s.replace("'", "''")


@dataclass
class Hit:
    source_id: str
    title: str
    chunk_index: int
    heading_path: str
    content: str
    tags: list[str]
    vector: np.ndarray | None = None
    score_dense: float = 0.0


class VectorStore:
    TABLE = "chunks"

    def __init__(self, db_dir: Path, dim: int = 1024):
        self._db = lancedb.connect(db_dir)
        if self.TABLE in self._db.table_names():
            self._table = self._db.open_table(self.TABLE)
        else:
            self._table = self._db.create_table(
                self.TABLE,
                schema=pa.schema(
                    [
                        ("vector", pa.list_(pa.float32(), dim)),
                        ("source_type", pa.string()),
                        ("source_id", pa.string()),
                        ("title", pa.string()),
                        ("chunk_index", pa.int32()),
                        ("heading_path", pa.string()),
                        ("content", pa.string()),
                        ("tags", pa.list_(pa.string())),
                        ("external_url", pa.string()),
                        ("content_hash", pa.string()),
                        ("updated_at", pa.timestamp("us")),
                    ]
                ),
            )

    def upsert(self, chunks: list[Chunk], vectors: np.ndarray) -> None:
        if not chunks:
            return
        vecs = np.asarray(vectors, dtype="float32")
        if vecs.shape[0] != len(chunks):
            raise ValueError("vectors 与 chunks 数量不一致")
        for sid in {c.source_id for c in chunks}:
            self.delete_by_source(sid)
        now = datetime.now(UTC)
        rows = [
            {
                "vector": vecs[i].tolist(),
                "source_type": "obsidian",
                "source_id": c.source_id,
                "title": c.title,
                "chunk_index": c.chunk_index,
                "heading_path": c.heading_path,
                "content": c.content,
                "tags": list(c.tags),
                "external_url": c.external_url,
                "content_hash": c.content_hash,
                "updated_at": now,
            }
            for i, c in enumerate(chunks)
        ]
        self._table.add(rows)

    def delete_by_source(self, source_id: str) -> None:
        self._table.delete(f"source_id = '{_esc(source_id)}'")

    def fetch_by_source(self, source_id: str) -> list[Hit]:
        """个人规模直接全表扫描后过滤；>5k 篇时再下推 SQL（见 handoff）。"""
        rows = [r for r in self._table.to_arrow().to_pylist()
                if r["source_id"] == source_id]
        rows.sort(key=lambda r: r["chunk_index"])
        return [
            Hit(
                source_id=r["source_id"], title=r["title"],
                chunk_index=r["chunk_index"], heading_path=r["heading_path"],
                content=r["content"], tags=list(r["tags"]),
                vector=np.asarray(r["vector"], dtype="float32"),
            )
            for r in rows
        ]

    def search(
        self, vector: np.ndarray, k: int, *, source_type: str | None = None,
        folder: str | None = None, tags: list[str] | None = None,
    ) -> list[Hit]:
        q = np.asarray(vector, dtype="float32")
        conds: list[str] = []
        if source_type is not None:
            conds.append(f"source_type = '{_esc(source_type)}'")
        if folder is not None:
            conds.append(f"source_id LIKE '{_esc(folder)}%'")
        builder = self._table.search(q).limit(k)
        if conds:
            builder = builder.where(" AND ".join(conds), prefilter=True)
        rows = builder.to_list()
        if tags is not None:  # tags 过滤 Python 侧后置（交集非空保留）
            want = set(tags)
            rows = [r for r in rows if want & set(r["tags"])]
        return [
            Hit(
                source_id=r["source_id"], title=r["title"],
                chunk_index=r["chunk_index"], heading_path=r["heading_path"],
                content=r["content"], tags=list(r["tags"]),
                score_dense=1.0 / (1.0 + r["_distance"]),
            )
            for r in rows
        ]

    def count(self) -> int:
        return self._table.count_rows()
