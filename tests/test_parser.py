from ragdb.ingest.parser import parse_note
from ragdb.ingest.schema import RawDocument


def _doc(body: str, fm: str = "") -> RawDocument:
    return RawDocument(
        source_type="obsidian", source_id="a.md", title="a",
        content=f"{fm}\n{body}".strip(),
    )


def test_heading_split_and_path():
    doc = _doc(
        "# 根标题\n引言\n## 架构\n架构内容\n### 数据管线\n管线内容\n## 测试\n测试内容"
    )
    note = parse_note(doc)
    paths = [s.heading_path for s in note.sections]
    assert paths == [
        "a > 根标题",
        "a > 根标题 > 架构",
        "a > 根标题 > 架构 > 数据管线",
        "a > 根标题 > 测试",
    ]
    assert "引言" in note.sections[0].content


def test_no_heading_single_section():
    note = parse_note(_doc("只是一段话"))
    assert len(note.sections) == 1
    assert note.sections[0].heading_path == "a"
    assert note.sections[0].level == 0


def test_frontmatter_wikilinks_tags():
    doc = RawDocument(
        source_type="obsidian", source_id="b.md", title="b", content=(
            "---\ntags: [RAG, 技术选型]\nstatus: 讨论\n---\n"
            "关联 [[技术栈方案]] 与 [[RAG项目/随手记|随手记]]"
        ),
    )
    note = parse_note(doc)
    assert note.tags == ["RAG", "技术选型"]
    assert note.wikilinks == ["技术栈方案", "RAG项目/随手记"]
    assert "tags:" not in note.sections[0].content  # frontmatter 剥离


def test_string_tags_normalized():
    doc = _doc("x", fm="---\ntags: 单标签\n---")
    assert parse_note(doc).tags == ["单标签"]


def test_preamble_before_first_heading():
    doc = _doc("开场白\n# 标题\n正文")
    note = parse_note(doc)
    assert note.sections[0].heading_path == "a" and "开场白" in note.sections[0].content
    assert note.sections[1].heading_path == "a > 标题"
