"""多源聚合连接器：N 个子连接器 + source_id 前缀化 + 跨源变更归并。"""

from __future__ import annotations

from dataclasses import replace

from ragdb.config import SourceConfig
from ragdb.ingest.connector import SourceConnector
from ragdb.ingest.schema import ChangeSet, FileStamp, RawDocument


class MultiSourceConnector(SourceConnector):
    """子连接器产出**不带前缀**的相对 source_id，本类统一加 `{name}/` 前缀。

    known 中不属于任何现有来源前缀的条目（来源被删除/改名/升级迁移）
    一律整体删除——孤儿清理自动化，无需手动 rebuild。
    """

    def __init__(self, items: list[tuple[SourceConfig, SourceConnector]]):
        self._items = items

    @property
    def source_prefixes(self) -> list[str]:
        return [f"{cfg.name}/" for cfg, _ in self._items]

    def fetch_all(self) -> list[RawDocument]:
        out: list[RawDocument] = []
        for cfg, conn in self._items:
            prefix = f"{cfg.name}/"
            for doc in conn.fetch_all():
                out.append(replace(doc, source_id=prefix + doc.source_id))
        return out

    def fetch_changes(self, known: dict[str, FileStamp]) -> ChangeSet:
        merged = ChangeSet()
        for cfg, conn in self._items:
            prefix = f"{cfg.name}/"
            sub_known = {k[len(prefix):]: v for k, v in known.items()
                         if k.startswith(prefix)}
            try:
                cs = conn.fetch_changes(sub_known)
            except Exception as e:  # noqa: BLE001 —— 单源故障隔离（终审 I1）
                merged.failed.append((cfg.name, str(e)))
                continue
            for d in cs.added:
                merged.added.append(replace(d, source_id=prefix + d.source_id))
            for d in cs.modified:
                merged.modified.append(replace(d, source_id=prefix + d.source_id))
            for old, d in cs.moved:
                merged.moved.append((prefix + old,
                                     replace(d, source_id=prefix + d.source_id)))
            merged.deleted.extend(prefix + p for p in cs.deleted)
            merged.unchanged += cs.unchanged
            merged.failed.extend(cs.failed)
        for k in known:  # 无主前缀 → 孤儿清理
            if not any(k.startswith(p) for p in self.source_prefixes):
                merged.deleted.append(k)
        return merged
