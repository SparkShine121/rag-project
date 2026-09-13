"""PDF 管线测试：按页切块、OCR 回退（注入 fake）、扫描版报错。真实 OCR 见 slow。"""

import pymupdf
import pytest

from ragdb.ingest.pdf import PdfParser
from ragdb.ingest.schema import RawDocument


def make_pdf(pages: list[str]) -> bytes:
    """程序化生成 PDF：每个元素一页，空串 = 无文本层页；空列表 = 0 页 PDF。"""
    if not pages:
        # pymupdf 拒绝保存 0 页文档——手工最小 PDF（容错解析可开）
        return b"%PDF-1.4\n1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n" \
               b"2 0 obj << /Type /Pages /Kids [] /Count 0 >> endobj\n" \
               b"trailer << /Size 3 /Root 1 0 R >>\n%%EOF"
    doc = pymupdf.open()
    for text in pages:
        page = doc.new_page()
        if text:
            # 默认 Helvetica 不含中文字形（提取会变占位点），用内置中文字体
            page.insert_text((72, 100), text, fontsize=14, fontname="china-s")
    return doc.tobytes()


def _doc(data: bytes) -> RawDocument:
    return RawDocument(source_type="github", source_id="docs/report.pdf",
                       title="report", content="", binary=data, metadata={})


def _parser(ocr_fn=None) -> PdfParser:
    return PdfParser(ocr_fn=ocr_fn, token_counter=len)


def test_text_layer_pdf_paginated():
    data = make_pdf(["第一页的关键内容", "第二页的关键内容"])
    chunks = _parser().split(_doc(data))
    assert len(chunks) == 2
    assert chunks[0].heading_path == "report.pdf > 第 1 页"
    assert chunks[1].heading_path == "report.pdf > 第 2 页"
    assert "第一页" in chunks[0].content and "第二页" in chunks[1].content
    assert [c.chunk_index for c in chunks] == [0, 1]


def test_empty_pages_with_ocr_fallback():
    data = make_pdf(["", ""])
    seen: list[int] = []

    def fake_ocr(png: bytes) -> str:
        seen.append(len(png))
        return "OCR 识别出的文本"

    chunks = _parser(ocr_fn=fake_ocr).split(_doc(data))
    assert len(seen) == 2 and all(s > 0 for s in seen)  # 每页渲染了位图
    assert len(chunks) == 2
    assert all("OCR 识别出的文本" in c.content for c in chunks)


def test_mixed_pages_ocr_only_for_blank():
    data = make_pdf(["有文本层的页", ""])
    calls: list = []
    chunks = _parser(ocr_fn=lambda png: calls.append(1) or "补充文本").split(_doc(data))
    assert len(calls) == 1  # 只有空白页走了 OCR
    assert "有文本层" in chunks[0].content and "补充文本" in chunks[1].content


def test_no_text_no_ocr_raises_scan_hint():
    data = make_pdf(["", ""])
    with pytest.raises(ValueError, match="扫描"):
        _parser(ocr_fn=None).split(_doc(data))


def test_empty_pdf_zero_pages():
    assert _parser().split(_doc(make_pdf([]))) == []


def test_real_ocr_apple_vision():
    """真实 Apple Vision OCR 冒烟：渲染大字文本 → OCR 识别关键数字。"""
    from ragdb.ingest.ocr import available, recognize_png

    if not available():
        pytest.skip("未安装 pyobjc-framework-Vision")
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 150), "RAGDB OCR TEST 20260908", fontsize=36)
    png = page.get_pixmap(dpi=200).tobytes("png")
    text = recognize_png(png)
    assert "20260908" in text.replace(" ", "")
