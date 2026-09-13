"""解析分发器：按扩展名/内容形态把文档路由到 md / PDF / 代码切块器。"""

from __future__ import annotations

from pathlib import Path

from ragdb.ingest.code import _LANG_BY_EXT
from ragdb.ingest.schema import Chunk, RawDocument


class IngestPipeline:
    def __init__(self, chunker, code_chunker, pdf_parser, token_counter=None):
        self._chunker = chunker
        self._code_chunker = code_chunker
        self._pdf_parser = pdf_parser
        self._counter = token_counter

    def _count(self, text: str) -> int:
        return len(text) if self._counter is None else self._counter(text)

    def chunk(self, doc: RawDocument) -> list[Chunk]:
        ext = Path(doc.source_id).suffix.lower()
        if ext == ".pdf" or doc.binary is not None:
            return self._pdf_parser.split(doc)
        if ext == ".md":
            from ragdb.ingest.parser import parse_note

            return self._chunker.split(parse_note(doc))
        if ext in _LANG_BY_EXT:
            return self._code_chunker.split(doc)
        # 白名单外的未知类型：内容原样成单块（不做语义切块）
        filename = Path(doc.source_id).name
        return [Chunk(
            source_id=doc.source_id, title=doc.title, chunk_index=0,
            heading_path=filename, content=doc.content,
            token_count=self._count(doc.content),
            tags=list(doc.metadata.get("tags", [])),
            external_url=doc.metadata.get("external_url"),
            content_hash=doc.content_hash,
        )]
