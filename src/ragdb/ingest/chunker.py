"""标题感知分块：过短并入、超长按段落二切。token 计数可注入（测试用 len）。"""

from __future__ import annotations

from collections.abc import Callable
from functools import lru_cache

from ragdb.ingest.schema import Chunk, ParsedNote

TokenCounter = Callable[[str], int]

DEFAULT_MIN_CHARS = 100
DEFAULT_MAX_TOKENS = 500


@lru_cache(maxsize=1)
def _default_counter() -> TokenCounter:
    """懒加载 bge-m3 同源 tokenizer 作 token 计数；仅真实同步路径触达。"""
    from transformers import AutoTokenizer

    tok = AutoTokenizer.from_pretrained("BAAI/bge-m3")

    def count(text: str) -> int:
        return len(tok(text)["input_ids"])

    return count


class Chunker:
    def __init__(
        self,
        token_counter: TokenCounter | None = None,
        min_chars: int = DEFAULT_MIN_CHARS,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ):
        self._counter = token_counter
        self._min_chars = min_chars
        self._max_tokens = max_tokens

    def _count(self, text: str) -> int:
        if self._counter is None:
            self._counter = _default_counter()
        return self._counter(text)

    def split(self, note: ParsedNote) -> list[Chunk]:
        chunks: list[Chunk] = []
        pending_short: list[str] = []  # 前置过短节，待并入下一个块

        def heading_of_last_section() -> str:
            return note.sections[-1].heading_path if note.sections else note.doc.title

        def new_chunk(content: str, heading_path: str) -> Chunk:
            return Chunk(
                source_id=note.doc.source_id,
                title=note.doc.title,
                chunk_index=len(chunks),
                heading_path=heading_path,
                content=content,
                token_count=self._count(content),
                tags=list(note.tags),
                external_url=note.doc.metadata.get("external_url"),
            )

        def consume_pending(heading_path: str, tail: str | None = None) -> None:
            """积压前置短节（可选拼接尾段）落成一个块；无积压且无尾段时不动。"""
            parts = [*pending_short]
            pending_short.clear()
            if tail is not None:
                parts.append(tail)
            if not parts:
                return
            chunks.append(new_chunk("\n\n".join(parts), heading_path))

        def split_long(content: str) -> list[str]:
            pieces: list[str] = []
            for para in content.split("\n\n"):
                if self._count(para) < self._max_tokens:
                    pieces.append(para)
                    continue
                # 超长段落按字符窗硬切（CJK 近似 1 字 1 token；对 8K 嵌入窗口无害）
                for i in range(0, len(para), self._max_tokens):
                    pieces.append(para[i:i + self._max_tokens])
            return pieces

        for section in note.sections:
            if not section.content:
                continue
            if len(section.content) < self._min_chars:
                if chunks:
                    prev = chunks[-1]
                    prev.content = f"{prev.content}\n\n{section.content}"
                    prev.token_count = self._count(prev.content)
                else:
                    pending_short.append(section.content)
                continue
            if self._count(section.content) < self._max_tokens:
                consume_pending(section.heading_path, tail=section.content)
            else:
                for piece in split_long(section.content):
                    consume_pending(section.heading_path, tail=piece)

        consume_pending(heading_of_last_section())
        return chunks
