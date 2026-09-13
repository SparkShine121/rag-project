"""变更归并：已知戳 vs 现盘戳 → 增/删/改/移/不变。Obsidian 与 GitHub 连接器共用。"""

from __future__ import annotations

from collections.abc import Callable

from ragdb.ingest.schema import ChangeSet, FileStamp, RawDocument


def build_change_set(
    known: dict[str, FileStamp],
    current: dict[str, FileStamp],
    fetch_doc: Callable[[str], RawDocument],
) -> ChangeSet:
    """current 的 hash 必须已解析；hash 相同即视为内容相同（mtime/size 由引擎刷新）。

    移动判定：新路径的 hash 与某条已删除路径一致 → moved（一条删除只消费一次）。
    hash 不同（移动+修改混合）→ 按新增+删除处理，宁重嵌入不漏更新。
    """
    cs = ChangeSet()
    deleted = [p for p in known if p not in current]
    deleted_hashes: dict[str, str] = {}
    for p in deleted:
        deleted_hashes.setdefault(known[p][2], p)
    consumed: set[str] = set()

    for path, stamp in current.items():
        if path in known:
            if stamp[2] == known[path][2]:
                cs.unchanged += 1
                continue
            cs.modified.append(fetch_doc(path))
            continue
        old = deleted_hashes.get(stamp[2])
        if old is not None and old not in consumed:
            consumed.add(old)
            cs.moved.append((old, fetch_doc(path)))
            continue
        cs.added.append(fetch_doc(path))

    cs.deleted = [p for p in deleted if p not in consumed]
    return cs
