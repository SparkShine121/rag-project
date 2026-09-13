"""PDF 管线：PyMuPDF 逐页提取 → 每页一块；无文本层 → OCR 回退 → 仍无 → failed。"""

from __future__ import annotations

import pymupdf

from ragdb.ingest.schema import Chunk, RawDocument


class PdfParser:
    def __init__(self, ocr_fn=None, token_counter=None, ocr_dpi: int = 200):
        self._ocr_fn = ocr_fn
        self._counter = token_counter
        self._ocr_dpi = ocr_dpi

    def _count(self, text: str) -> int:
        return len(text) if self._counter is None else self._counter(text)

    def split(self, doc: RawDocument) -> list[Chunk]:
        """逐页切块：heading_path = "{文件名} > 第 N 页"。

        无文本层页：有 ocr_fn → 渲染位图走 OCR 回退；无 ocr_fn 且整份文件
        提不出任何文本 → 抛 ValueError（"疑似扫描版"），由引擎进 failed，
        绝不静默丢内容。混合文件中个别扫描页在无 OCR 时跳过。
        """
        if doc.binary is None:
            raise ValueError(f"PDF 文档缺少二进制内容: {doc.source_id}")
        pdf = pymupdf.open(stream=doc.binary, filetype="pdf")
        stem = doc.source_id.rsplit("/", 1)[-1]
        chunks: list[Chunk] = []
        extracted_any = False
        scanned_pages = 0

        for idx, page in enumerate(pdf, start=1):
            text = page.get_text().strip()
            if text:
                extracted_any = True
            elif self._ocr_fn is not None:
                png = page.get_pixmap(dpi=self._ocr_dpi).tobytes("png")
                text = (self._ocr_fn(png) or "").strip()
                if text:
                    extracted_any = True
            else:
                scanned_pages += 1
                continue
            if not text:
                continue
            chunks.append(Chunk(
                source_id=doc.source_id, title=doc.title, chunk_index=len(chunks),
                heading_path=f"{stem} > 第 {idx} 页", content=text,
                token_count=self._count(text),
                tags=list(doc.metadata.get("tags", [])),
                external_url=doc.metadata.get("external_url"),
                content_hash=doc.content_hash,
            ))

        if not extracted_any and scanned_pages:
            raise ValueError(
                f"疑似扫描版 PDF（无文本层）: {doc.source_id}——"
                f"安装 pyobjc-framework-Vision 以启用 Apple Vision OCR 回退，"
                f"或将其移出知识源"
            )
        return chunks
