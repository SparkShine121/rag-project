"""代码启发式切块：顶级定义（def/class/function/func/fn）对齐 + 行窗口兜底。"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from ragdb.ingest.schema import Chunk, RawDocument

TokenCounter = None  # 类型占位：Callable[[str], int]


@lru_cache(maxsize=1)
def _default_counter():
    from ragdb.ingest.chunker import _default_counter

    return _default_counter()


# 语言 → 顶级定义正则（kind + sym 命名组；只匹配零缩进行）
_DEF_PATTERNS: dict[str, list[re.Pattern]] = {
    "python": [re.compile(r"^(?P<kind>def|class)\s+(?P<sym>\w+)")],
    "javascript": [re.compile(
        r"^(?:export\s+)?(?:default\s+)?(?P<kind>async\s+function|function|class)\s+(?P<sym>\w+)")],
    "go": [re.compile(r"^(?P<kind>func)\s+(?:\([^)]*\)\s*)?(?P<sym>\w+)")],
    "rust": [re.compile(r"^(?:pub\s+)?(?P<kind>fn|struct|enum|trait|impl)\s+(?P<sym>\w+)")],
    "java": [re.compile(r"^(?P<kind>class|interface|enum)\s+(?P<sym>\w+)")],
}

_LANG_BY_EXT = {
    ".py": "python", ".ts": "javascript", ".tsx": "javascript", ".js": "javascript",
    ".jsx": "javascript", ".go": "go", ".rs": "rust", ".java": "java",
}


class CodeChunker:
    def __init__(self, token_counter=None, max_tokens: int = 500):
        self._counter = token_counter
        self._max_tokens = max_tokens

    def _count(self, text: str) -> int:
        if self._counter is None:
            self._counter = _default_counter()
        return self._counter(text)

    def split(self, doc: RawDocument) -> list[Chunk]:
        ext = Path(doc.source_id).suffix.lower()
        lang = _LANG_BY_EXT.get(ext, "text")
        patterns = _DEF_PATTERNS.get(lang, [])
        lines = doc.content.splitlines(keepends=True)

        boundaries: list[tuple[int, str | None]] = [(0, None)]
        if patterns:
            for i, line in enumerate(lines):
                for pat in patterns:
                    m = pat.match(line)
                    if m:
                        boundaries.append((i, f"{m.group('kind')} {m.group('sym')}"))
                        break

        chunks: list[Chunk] = []

        def emit(text: str, sym: str | None) -> None:
            if not text.strip():
                return
            heading = Path(doc.source_id).name
            if sym:
                heading = f"{heading} > {sym}"
            chunks.append(Chunk(
                source_id=doc.source_id, title=doc.title, chunk_index=len(chunks),
                heading_path=heading, content=text,
                token_count=self._count(text),
                tags=list(doc.metadata.get("tags", [])),
                external_url=doc.metadata.get("external_url"),
                content_hash=doc.content_hash,
            ))

        for j, (start, sym) in enumerate(boundaries):
            end = boundaries[j + 1][0] if j + 1 < len(boundaries) else len(lines)
            segment = lines[start:end]
            text = "".join(segment)
            if not text.strip():
                continue
            if self._count(text) <= self._max_tokens:
                emit(text, sym)
                continue
            # 行窗口兜底：按 token 累积切分，符号名继承
            buf: list[str] = []
            used = 0
            for line in segment:
                lt = self._count(line)
                if buf and used + lt > self._max_tokens:
                    emit("".join(buf), sym)
                    buf, used = [], 0
                buf.append(line)
                used += lt
            emit("".join(buf), sym)
        return chunks
