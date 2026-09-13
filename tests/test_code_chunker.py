"""CodeChunker 启发式切块测试：顶级定义对齐 + 行窗口兜底。"""

from pathlib import Path

from ragdb.ingest.code import CodeChunker
from ragdb.ingest.schema import RawDocument

PY = (
    "import os\n\n\n"
    "def parse_args(argv):\n"
    '    """解析参数。"""\n'
    "    return argv\n\n\n"
    "class Runner:\n"
    "    def run(self):\n"
    "        return 1\n\n\n"
    "def main():\n"
    "    Runner().run()\n"
)


def _doc(path: str, content: str) -> RawDocument:
    return RawDocument(source_type="folder", source_id=path,
                       title=Path(path).stem, content=content, metadata={})


def _chunks(path: str, content: str, max_tokens: int = 500):
    return CodeChunker(token_counter=len, max_tokens=max_tokens).split(_doc(path, content))


def test_python_def_boundaries_with_symbols():
    chunks = _chunks("src/cli.py", PY)
    assert len(chunks) >= 3
    assert any("def parse_args" in c.heading_path for c in chunks)
    assert any("class Runner" in c.heading_path for c in chunks)
    assert any("def main" in c.heading_path for c in chunks)
    assert all(c.source_id == "src/cli.py" for c in chunks)


def test_small_file_single_chunk():
    chunks = _chunks("a.py", "x = 1\n")
    assert len(chunks) == 1
    assert chunks[0].content == "x = 1\n"
    assert chunks[0].heading_path == "a.py"  # 无定义 → 文件名标题链


def test_line_window_fallback_for_oversized_block():
    big = "def big():\n" + "\n".join(f"    x{i} = {i}" for i in range(2000)) + "\n"
    chunks = _chunks("big.py", big, max_tokens=200)
    assert len(chunks) >= 2
    assert all(c.token_count <= 200 for c in chunks)
    assert all("def big" in c.heading_path for c in chunks)  # 兜底块继承符号名


def test_no_defs_language_uses_line_window():
    data = "\n".join(f"line {i}: value" for i in range(1500)) + "\n"
    chunks = _chunks("conf.yaml", data, max_tokens=300)
    assert len(chunks) >= 2
    assert all(c.token_count <= 300 for c in chunks)


def test_indices_sequential_and_hash_inherited():
    chunks = _chunks("src/cli.py", PY)
    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))
    assert all(c.content_hash == _doc("src/cli.py", PY).content_hash for c in chunks)


def test_go_and_ts_symbols():
    go = "package main\n\nfunc Run() error {\n\treturn nil\n}\n"
    ts = "export function helper(x: number): number {\n  return x\n}\n"
    assert any("func Run" in c.heading_path for c in _chunks("m.go", go))
    assert any("function helper" in c.heading_path for c in _chunks("m.ts", ts))
