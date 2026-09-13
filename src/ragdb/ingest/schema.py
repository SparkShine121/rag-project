"""数据模型：连接器/解析/切块/存储共用的类型。"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

FileStamp = tuple[float, int, str]  # (mtime, size, content_hash)


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass
class RawDocument:
    source_type: str
    source_id: str
    title: str
    content: str
    metadata: dict = field(default_factory=dict)
    hash_override: str | None = None  # GitHub 源用 git blob sha（同 blob = 同内容）
    binary: bytes | None = None       # 二进制内容（如 PDF），不进 content 字符串

    @property
    def content_hash(self) -> str:
        if self.hash_override is not None:
            return self.hash_override
        return content_hash(self.content)


@dataclass
class ChangeSet:
    added: list[RawDocument] = field(default_factory=list)
    modified: list[RawDocument] = field(default_factory=list)
    moved: list[tuple[str, RawDocument]] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    unchanged: int = 0
    failed: list[tuple[str, str]] = field(default_factory=list)  # (来源名, 原因)


@dataclass
class Section:
    heading_path: str
    content: str
    level: int


@dataclass
class ParsedNote:
    doc: RawDocument
    frontmatter: dict
    wikilinks: list[str]
    tags: list[str]
    sections: list[Section]


@dataclass
class Chunk:
    source_id: str
    title: str
    chunk_index: int
    heading_path: str
    content: str
    token_count: int
    tags: list[str] = field(default_factory=list)
    external_url: str | None = None
    content_hash: str = ""  # 所属文档内容 hash，入 LanceDB content_hash 列
