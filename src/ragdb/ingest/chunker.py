"""标题感知分块：过短并入、超长按段落二切。token 计数可注入（测试用 len）。"""

from __future__ import annotations

from collections.abc import Callable
from functools import lru_cache

from ragdb.ingest.schema import Chunk, ParsedNote

TokenCounter = Callable[[str], int]


@lru_cache(maxsize=1)
def _default_counter() -> TokenCounter:
    """懒加载 bge-m3 同源 tokenizer 作 token 计数；仅真实同步路径触达。"""
    from transformers import AutoTokenizer

    tok = AutoTokenizer.from_pretrained("BAAI/bge-m3")

    def count(text: str) -> int:
        return len(tok(text)["input_ids"])

    return count


class Chunker:
    def __init__(self, token_counter: TokenCounter | None = None):
        self._counter = token_counter

    def _count(self, text: str) -> int:
        if self._counter is None:
            self._counter = _default_counter()
        return self._counter(text)

    def split(self, note: ParsedNote) -> list[Chunk]:
        max_tokens = 500  # Global Constraint；与 Settings.chunk.max_tokens 同值
        min_chars = 100
        chunks: list[Chunk] = []
        pending_short: list[str] = []  # 前置过短节，待并入下一个块

        def make(content: str, heading_path: str) -> Chunk:
            joined = "\n\n".join([*pending_short, content]) if pending_short else content
            pending_short.clear()
            return Chunk(
                source_id=note.doc.source_id,
                title=note.doc.title,
                chunk_index=len(chunks),
                heading_path=heading_path,
                content=joined,
                token_count=self._count(joined),
                tags=list(note.tags),
                external_url=note.doc.metadata.get("external_url"),
            )

        def split_long(content: str) -> list[str]:
            pieces: list[str] = []
            for para in content.split("\n\n"):
                if self._count(para) < max_tokens:
                    pieces.append(para)
                    continue
                # 超长段落按字符窗硬切（CJK 近似 1 字 1 token；对 8K 嵌入窗口无害）
                for i in range(0, len(para), max_tokens):
                    pieces.append(para[i:i + max_tokens])
            return pieces

        for section in note.sections:
            if not section.content:
                continue
            if len(section.content) < min_chars:
                if chunks:
                    prev = chunks[-1]
                    prev.content = f"{prev.content}\n\n{section.content}"
                    prev.token_count = self._count(prev.content)
                else:
                    pending_short.append(section.content)
                continue
            if self._count(section.content) < max_tokens:
                chunks.append(make(section.content, section.heading_path))
            else:
                for piece in split_long(section.content):
                    chunks.append(make(piece, section.heading_path))

        if pending_short and not chunks:
            chunks.append(make(pending_short[-1], note.sections[-1].heading_path
                               if note.sections else note.doc.title))
        return chunks
