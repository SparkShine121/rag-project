"""解析分发器测试：按扩展名/内容形态路由到 md/PDF/代码切块器。"""

import pymupdf

from ragdb.ingest.chunker import Chunker
from ragdb.ingest.code import CodeChunker
from ragdb.ingest.pdf import PdfParser
from ragdb.ingest.pipeline import IngestPipeline
from ragdb.ingest.schema import RawDocument

PY = "def parse(x):\n    return x\n"


def _doc(sid: str, content: str = "", binary: bytes | None = None) -> RawDocument:
    return RawDocument(source_type="folder", source_id=sid,
                       title=sid.rsplit("/", 1)[-1], content=content,
                       binary=binary, metadata={})


def _pipeline() -> IngestPipeline:
    return IngestPipeline(
        chunker=Chunker(token_counter=len),
        code_chunker=CodeChunker(token_counter=len),
        pdf_parser=PdfParser(token_counter=len),
    )


def _pdf_bytes(text: str) -> bytes:
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 100), text, fontsize=14, fontname="china-s")
    return doc.tobytes()


def test_md_routes_to_markdown_chunker():
    chunks = _pipeline().chunk(_doc("notes/a.md", "# 标题\n正文内容足够长一些。"))
    assert len(chunks) == 1
    assert "标题" in chunks[0].heading_path  # md 走标题解析（代码切块器不会）


def test_pdf_routes_to_pdf_parser():
    chunks = _pipeline().chunk(_doc("docs/r.pdf", binary=_pdf_bytes("页内容")))
    assert chunks[0].heading_path == "r.pdf > 第 1 页"


def test_code_routes_to_code_chunker():
    chunks = _pipeline().chunk(_doc("src/m.py", PY))
    assert any("def parse" in c.heading_path for c in chunks)


def test_unknown_ext_passthrough_single_chunk():
    chunks = _pipeline().chunk(_doc("data.xyz", "未知扩展名的内容原样成块"))
    assert len(chunks) == 1
    assert chunks[0].content == "未知扩展名的内容原样成块"
    assert chunks[0].heading_path == "data.xyz"


def test_binary_without_content_still_routes_pdf():
    doc = _doc("b.pdf", content="", binary=_pdf_bytes("二进制内容"))
    chunks = _pipeline().chunk(doc)
    assert chunks[0].heading_path == "b.pdf > 第 1 页"
    assert doc.content == ""  # 二进制不进 content 字符串
