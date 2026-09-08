from ragdb.ingest.chunker import Chunker
from ragdb.ingest.parser import parse_note
from ragdb.ingest.schema import RawDocument


def _note(body: str, title="n"):
    return parse_note(RawDocument("obsidian", "n.md", title, body))


def test_short_section_merges_into_previous():
    note = _note("## A\n" + "长内容" * 40 + "\n## B\n短")
    chunks = Chunker(token_counter=len).split(note)
    assert len(chunks) == 1
    assert "短" in chunks[0].content and "长内容" in chunks[0].content


def test_leading_short_section_merges_forward():
    note = _note("## A\n短\n## B\n" + "内容" * 80)
    chunks = Chunker(token_counter=len).split(note)
    assert len(chunks) == 1 and chunks[0].content.startswith("短")


def test_long_section_split_by_paragraph():
    paras = "\n\n".join("段" * 300 for _ in range(3))  # 每段 300 字 < 500
    note = _note(f"## 长节\n\n{paras}\n\n{'尾' * 600}")
    chunks = Chunker(token_counter=len).split(note)
    assert len(chunks) >= 2
    assert all(c.token_count <= 500 for c in chunks)


def test_metadata_inherited():
    doc = RawDocument("obsidian", "t.md", "t", "## X\n内容" * 1,
                      metadata={"external_url": "https://e/x"})
    note = parse_note(doc)
    note.tags = ["T1"]
    chunks = Chunker(token_counter=len).split(note)
    assert chunks[0].source_id == "t.md" and chunks[0].chunk_index == 0
    assert chunks[0].heading_path == "t > X" and chunks[0].tags == ["T1"]
    assert chunks[0].external_url == "https://e/x" and chunks[0].title == "t"


def test_empty_note_returns_empty():
    assert Chunker(token_counter=len).split(parse_note(
        RawDocument("obsidian", "e.md", "e", ""))) == []


def test_multiple_leading_short_sections_no_duplicate():
    note = _note("## A\n短一\n## B\n短二\n## C\n短三")
    chunks = Chunker(token_counter=len).split(note)
    assert len(chunks) == 1
    c = chunks[0].content
    assert c.count("短一") == 1 and c.count("短二") == 1 and c.count("短三") == 1


def test_chunker_params_override_defaults():
    body = "## A\n" + "字" * 120 + "\n## B\n" + "字" * 50
    assert len(Chunker(token_counter=len).split(_note(body))) == 1  # 50<100 默认并入 A
    strict = Chunker(token_counter=len, min_chars=40).split(_note(body))
    assert len(strict) == 2  # 50>=40 独立成块
    long_note = _note("## A\n" + "字" * 300)
    assert all(
        c.token_count <= 200
        for c in Chunker(token_counter=len, max_tokens=200).split(long_note)
    )
