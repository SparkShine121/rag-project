"""增量同步引擎：增/删/改/移四路处理；移动零重嵌入；单文件失败不中断。"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import UTC, datetime

import numpy as np

from ragdb.ingest.parser import parse_note


@dataclass
class SyncReport:
    added: int = 0
    updated: int = 0
    deleted: int = 0
    moved: int = 0
    failed: list[tuple[str, str]] = field(default_factory=list)
    duration: float = 0.0


def _empty_vecs(embedder, n: int) -> np.ndarray:
    return np.zeros((n, embedder.dim), dtype="float32")


class SyncEngine:
    def __init__(self, connector, embedder, store, state, chunker):
        self._connector = connector
        self._embedder = embedder
        self._store = store
        self._state = state
        self._chunker = chunker

    def run(self, full: bool = False) -> SyncReport:
        t0 = time.perf_counter()
        report = SyncReport()
        try:
            if full:
                for sid in list(self._state.get_all()):
                    self._store.delete_by_source(sid)
                    self._state.delete(sid)
            cs = self._connector.fetch_changes(self._state.get_all())
            report.failed.extend(cs.failed)  # 单源故障隔离的失败项（终审 I1）
        except Exception as e:  # noqa: BLE001 —— 扫描级失败：整轮终止但结构化汇报
            report.failed.append(("<scan>", str(e)))
            report.duration = time.perf_counter() - t0
            return report

        def index(doc) -> int:
            if doc.metadata.get("read_error"):
                raise ValueError("文件不是有效 UTF-8 文本")
            # mtime/size 为 obsidian 文件系统语义；github 等无此键时用内容长度兜底
            # （变更检测以 content_hash 为准，戳仅作簿记）
            mtime = doc.metadata.get("mtime", 0.0)
            size = doc.metadata.get("size", len(doc.content.encode("utf-8")))
            chunks = self._chunker.split(parse_note(doc))
            if not chunks:  # 清空正文 → 旧向量必须清除（终审 I1）
                self._store.delete_by_source(doc.source_id)
                self._state.upsert(doc.source_id, mtime, size, doc.content_hash, 0)
                return 0
            vecs = self._embedder.embed([c.content for c in chunks])
            self._store.upsert(chunks, vecs)
            self._state.upsert(doc.source_id, mtime, size, doc.content_hash,
                               len(chunks))
            return len(chunks)

        for doc in cs.added:
            try:
                index(doc)
                report.added += 1
            except Exception as e:  # noqa: BLE001 —— 单文件失败隔离
                report.failed.append((doc.source_id, str(e)))

        for doc in cs.modified:
            try:
                index(doc)
                report.updated += 1
            except Exception as e:  # noqa: BLE001 —— 单文件失败隔离
                report.failed.append((doc.source_id, str(e)))

        for old_id, doc in cs.moved:
            try:
                if doc.metadata.get("read_error"):
                    raise ValueError("文件不是有效 UTF-8 文本")
                chunks = self._chunker.split(parse_note(doc))
                old_hits = self._store.fetch_by_source(old_id)
                if (len(old_hits) == len(chunks)
                        and all(h.vector is not None for h in old_hits)):
                    vecs = np.stack([h.vector for h in old_hits]) if chunks \
                        else _empty_vecs(self._embedder, 0)
                else:  # 内容变了（移动+修改混合）：回退重嵌入
                    vecs = (
                        self._embedder.embed([c.content for c in chunks])
                        if chunks else _empty_vecs(self._embedder, 0)
                    )
                self._store.delete_by_source(old_id)
                self._store.upsert(chunks, vecs)
                self._state.delete(old_id)
                self._state.upsert(
                    doc.source_id,
                    doc.metadata.get("mtime", 0.0),
                    doc.metadata.get("size", len(doc.content.encode("utf-8"))),
                    doc.content_hash, len(chunks),
                )
                report.moved += 1
            except Exception as e:  # noqa: BLE001 —— 单文件失败隔离
                report.failed.append((doc.source_id, str(e)))

        for sid in cs.deleted:
            try:
                self._store.delete_by_source(sid)
                self._state.delete(sid)
                report.deleted += 1
            except Exception as e:  # noqa: BLE001 —— 删除失败隔离
                report.failed.append((sid, str(e)))

        self._state.set_meta("last_sync_at", datetime.now(UTC).isoformat())
        report.duration = time.perf_counter() - t0
        return report
