# ragdb v1 Implementation Plan

> **For agentic workers:** 用 dev-workflow 阶段四（TDD 实现）逐任务执行本计划。步骤用 checkbox（`- [ ]`）语法跟踪。

**Goal:** 本地个人 RAG 数据库——Obsidian vault 向量化检索，经 stdio MCP / HTTP MCP / REST 三通道供多 agent 只读调用。

**Architecture:** 薄壳（api/mcp/cli）+ 核心库（sync/retrieve/models/store/ingest/config）。serve 进程为唯一写者（30s 同步循环）；MCP 进程只读；vault 全链路只读。

**Tech Stack:** Python 3.12（uv）· FlagEmbedding（BAAI/bge-m3 + bge-reranker-v2-m3, MPS fp16）· LanceDB + SQLite · FastAPI + FastMCP · pydantic v2 · pytest。

## Global Constraints（每个任务隐式继承，精确值从规格拷贝）

- Python `3.12`；包管理 uv；布局 `src/ragdb/`，测试镜像于 `tests/`。
- 模型：嵌入 `BAAI/bge-m3`（1024 维，L2 归一化）、重排 `BAAI/bge-reranker-v2-m3`；`device=mps`、`dtype=float16`（配置可降 `float32`）；嵌入 batch=32。
- 常量：端口 `8770` 仅绑 `127.0.0.1`；`interval_secs=30`；`recall_k=20`；`top_k=5`；`token_budget=3000`；chunk `min_chars=100` / `max_tokens=500` / `short_note_tokens=600`。
- vault 只读；路径处理一律 `pathlib`（vault 路径含空格与中文）；跳过 `.obsidian/`、`.trash/`、`.` 开头隐藏项、非 `.md` 文件。
- 单写者：仅 serve 进程与持 `ragdb.lock` 文件锁的 CLI 可写 LanceDB；MCP/HTTP 只读。
- MCP 只读三工具 `search` / `get_note` / `list_notes`；`/mcp`（Streamable HTTP）与 stdio 共用同一套工具函数。
- 快速测试禁止网络与模型下载：用 `tests/helpers.py` 的 `FakeEmbedder` / `FakeReranker` / `make_vault()`；真实模型测试一律 `@pytest.mark.slow` 且需环境变量 `RAGDB_SLOW=1`。
- 数据目录默认 `~/Library/Application Support/ragdb`；**测试中一律注入 tmp_path，绝不写真目录**。
- 分支：每任务从 `dev` 拉 `feature/<任务名>`，完成后合并回 `dev`。提交信息中文，结尾加 `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`。
- spec：`docs/superpowers/specs/2026-09-08-rag-database-design.md`（歧义以 spec 为准）。

---

### Task 1: 项目脚手架

**Files:**
- Create: `pyproject.toml`, `src/ragdb/__init__.py`, `tests/__init__.py`, `tests/test_smoke.py`, `.gitignore`, `.python-version`

**Interfaces:**
- Produces: 可 `uv run pytest` 的空项目；`ragdb.__version__ = "0.1.0"`；console scripts 占位在 Task 14 接线（本任务先声明 `[project.scripts]` 会因模块不存在而失败——**本任务不声明 scripts**，Task 14 再加）。

- [ ] **Step 1: pyproject.toml**

```toml
[project]
name = "ragdb"
version = "0.1.0"
description = "个人 RAG 数据库：Obsidian 向量化检索，MCP/HTTP 多 agent 接入"
requires-python = ">=3.12,<3.13"
dependencies = [
    "flagembedding>=1.3",
    "torch>=2.6",
    "lancedb>=0.20",
    "pyarrow>=17",
    "numpy>=1.26",
    "pydantic>=2.8",
    "pydantic-settings>=2.4",
    "python-frontmatter>=1.1",
    "fastapi>=0.115",
    "uvicorn>=0.30",
    "mcp>=1.9",
    "httpx>=0.27",
]

[project.optional-dependencies]
dev = ["pytest>=8", "ruff>=0.6"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/ragdb"]

[tool.pytest.ini_options]
testpaths = ["tests"]
markers = ["slow: 真实模型慢速测试，需 RAGDB_SLOW=1"]

[tool.ruff]
line-length = 100
target-version = "py312"
src = ["src", "tests"]
```

`.gitignore`：`.venv/`, `__pycache__/`, `.pytest_cache/`, `.ruff_cache/`, `*.egg-info/`, `.superpowers/`。`.python-version` 内容：`3.12`。

- [ ] **Step 2: 失败测试** `tests/test_smoke.py`

```python
import ragdb

def test_package_importable():
    assert ragdb.__version__ == "0.1.0"
```

- [ ] **Step 3: 确认失败**：`uv sync --extra dev && uv run pytest -q` → FAIL（`__version__` 不存在）
- [ ] **Step 4: 最小实现** `src/ragdb/__init__.py`：`__version__ = "0.1.0"`
- [ ] **Step 5: 确认通过**：`uv run pytest -q` → 1 passed；`uv run ruff check .` → 0 errors
- [ ] **Step 6: 提交** `chore: 项目脚手架——uv/hatch/ruff/pytest 就绪`

---

### Task 2: config——Settings 与 ragdb.toml

**Files:**
- Create: `src/ragdb/config.py`, `tests/test_config.py`

**Interfaces:**
- Consumes: 无
- Produces: `Settings.load(path: Path | None = None) -> Settings`；字段与默认值（spec §5.1）：`vault_path: Path`（默认 `~/Documents/Obsidian Vault`）、`data_dir: Path`（默认 `~/Library/Application Support/ragdb`）、`port=8770`、`interval_secs=30`、`recall_k=20`、`top_k=5`、`token_budget=3000`、`chunk_min_chars=100`、`chunk_max_tokens=500`、`short_note_tokens=600`、`embed_model="BAAI/bge-m3"`、`rerank_model="BAAI/bge-reranker-v2-m3"`、`device="mps"`、`dtype="float16"`、`embed_batch=32`。`ChunkConfig` 子模型含 `min_chars/max_tokens/short_note_tokens`。嵌套与扁平都行，**字段名以上述为准**。

- [ ] **Step 1: 失败测试**

```python
from pathlib import Path
import pytest
from ragdb.config import Settings

def test_defaults():
    s = Settings.load(path=None)
    assert s.port == 8770 and s.interval_secs == 30
    assert s.recall_k == 20 and s.top_k == 5 and s.token_budget == 3000
    assert s.chunk.min_chars == 100 and s.chunk.max_tokens == 500
    assert s.chunk.short_note_tokens == 600
    assert s.embed_model == "BAAI/bge-m3"
    assert s.rerank_model == "BAAI/bge-reranker-v2-m3"
    assert s.device == "mps" and s.dtype == "float16" and s.embed_batch == 32

def test_toml_override(tmp_path: Path):
    cfg = tmp_path / "ragdb.toml"
    cfg.write_text('port = 9000\ntop_k = 3\n', encoding="utf-8")
    s = Settings.load(path=cfg)
    assert s.port == 9000 and s.top_k == 3
    assert s.interval_secs == 30  # 未覆盖项保持默认

def test_dtype_rejects_invalid(tmp_path: Path):
    cfg = tmp_path / "ragdb.toml"
    cfg.write_text('dtype = "int8"\n', encoding="utf-8")
    with pytest.raises(Exception):
        Settings.load(path=cfg)
```

- [ ] **Step 2: 确认失败**：`uv run pytest tests/test_config.py -q` → FAIL（模块不存在）
- [ ] **Step 3: 最小实现**：pydantic-settings `BaseSettings`，`model_config = SettingsConfigDict(toml_file=...)` 或手动 `tomllib` 读取 + `Settings(**data)`（后者更直白，推荐）；`chunk: ChunkConfig = Field(default_factory=ChunkConfig)`；`dtype` 用 `Literal["float16", "float32"]`。env 前缀 `RAGDB_`。
- [ ] **Step 4: 确认通过** + `uv run ruff check .`
- [ ] **Step 5: 提交** `feat: config——Settings 与 ragdb.toml 加载`

---

### Task 3: ingest——schema 与 parser

**Files:**
- Create: `src/ragdb/ingest/__init__.py`, `src/ragdb/ingest/schema.py`, `src/ragdb/ingest/parser.py`, `tests/test_parser.py`

**Interfaces:**
- Produces（后续任务签名依赖，逐字使用）：

```python
def content_hash(text: str) -> str                      # sha256 hex
@dataclass RawDocument:  # source_type: str, source_id: str, title: str, content: str,
                        # metadata: dict = field(default_factory=dict)
                        # property content_hash -> str
FileStamp = tuple[float, int, str]                      # (mtime, size, content_hash)
@dataclass ChangeSet:    # added: list[RawDocument]; modified: list[RawDocument];
                        # moved: list[tuple[str, RawDocument]]; deleted: list[str]; unchanged: int
@dataclass Section:      # heading_path: str, content: str, level: int
@dataclass ParsedNote:   # doc: RawDocument, frontmatter: dict, wikilinks: list[str],
                        # tags: list[str], sections: list[Section]
def parse_note(doc: RawDocument) -> ParsedNote
```

- 切块语义：正文按 1-3 级标题切 Section；`heading_path` 形如 `"标题 > H2 > H3"`（stack 拼接）；无标题正文整体一个 Section（`heading_path=title`，`level=0`）；frontmatter 不进正文；tags 取 frontmatter 的 `tags`（str 或 list 归一为 `list[str]`）；wikilink 正则 `\[\[([^\]\|#]+)`（去首尾空白）。

- [ ] **Step 1: 失败测试**

```python
from ragdb.ingest.schema import RawDocument
from ragdb.ingest.parser import parse_note

def _doc(body: str, fm: str = "") -> RawDocument:
    return RawDocument(source_type="obsidian", source_id="a.md", title="a",
                       content=f"{fm}\n{body}".strip())

def test_heading_split_and_path():
    doc = _doc("# 根标题\n引言\n## 架构\n架构内容\n### 数据管线\n管线内容\n## 测试\n测试内容")
    note = parse_note(doc)
    paths = [s.heading_path for s in note.sections]
    assert paths == ["a > 根标题", "a > 根标题 > 架构", "a > 根标题 > 架构 > 数据管线", "a > 根标题 > 测试"]
    assert "引言" in note.sections[0].content

def test_no_heading_single_section():
    note = parse_note(_doc("只是一段话"))
    assert len(note.sections) == 1
    assert note.sections[0].heading_path == "a"
    assert note.sections[0].level == 0

def test_frontmatter_wikilinks_tags():
    doc = RawDocument(source_type="obsidian", source_id="b.md", title="b", content=(
        "---\ntags: [RAG, 技术选型]\nstatus: 讨论\n---\n"
        "关联 [[技术栈方案]] 与 [[RAG项目/随手记|随手记]]"))
    note = parse_note(doc)
    assert note.tags == ["RAG", "技术选型"]
    assert note.wikilinks == ["技术栈方案", "RAG项目/随手记"]
    assert "tags:" not in note.sections[0].content  # frontmatter 剥离

def test_string_tags_normalized():
    doc = _doc("x", fm="---\ntags: 单标签\n---")
    assert parse_note(doc).tags == ["单标签"]
```

- [ ] **Step 2: 确认失败**
- [ ] **Step 3: 最小实现**：frontmatter 用 `python-frontmatter`（`frontmatter.loads(doc.content)`）；标题行正则 `^(#{1,3})\s+(.+)$`（`re.MULTILINE`），逐行扫描维护 stack：level<=现有栈顶深度则弹栈后压入；Section.content 为该标题至下一标题前正文（不含标题行，strip 后保留空串过滤）。无任何标题→单 Section。
- [ ] **Step 4: 确认通过** + ruff
- [ ] **Step 5: 提交** `feat: ingest——schema 数据模型与 md 解析器`

---

### Task 4: ingest——Chunker

**Files:**
- Create: `src/ragdb/ingest/chunker.py`, `tests/test_chunker.py`

**Interfaces:**
- Consumes: Task 3 的 `ParsedNote/Section/Chunk 所需字段`
- Produces:

```python
TokenCounter = Callable[[str], int]
class Chunker:
    def __init__(self, token_counter: TokenCounter | None = None): ...
    def split(self, note: ParsedNote) -> list[Chunk]
```

- 规则：逐 Section 产出 Chunk（`chunk_index` 0 起按序）；Section 内容 `token_count < max_tokens` 且字符数 `>= min_chars` → 直接成块；字符数 `< min_chars` → 并入**上一个块**（无上块则缓存待并入下块，收尾时仍孤立则独立成块）；`token_count >= max_tokens` → 按 `\n\n` 段落二级切分，仍超长则按 `max_tokens` 硬切。`heading_path`/`tags`/`title`（=note.doc.title）/`external_url`（=note.doc.metadata.get("external_url")）逐块继承。默认 token_counter 懒加载 bge-m3 tokenizer（`functools.lru_cache` 包裹，import transformers 放函数内）；测试注入 `len`。

- [ ] **Step 1: 失败测试**

```python
from ragdb.ingest.schema import RawDocument
from ragdb.ingest.parser import parse_note
from ragdb.ingest.chunker import Chunker

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
    paras = "\n\n".join("段" * 300 for _ in range(3))  # 每段 len=300 > max_tokens=500? 300<500
    note = _note(f"## 长节\n\n{paras}\n\n{'尾' * 600}")
    chunks = Chunker(token_counter=len).split(note)
    assert len(chunks) >= 2
    assert all(c.token_count <= 500 for c in chunks)

def test_metadata_inherited():
    doc = RawDocument("obsidian", "t.md", "t", "## X\n内容" * 1,
                     metadata={"external_url": "https://e/x"})
    note = parse_note(doc); note.tags = ["T1"]
    chunks = Chunker(token_counter=len).split(note)
    assert chunks[0].source_id == "t.md" and chunks[0].chunk_index == 0
    assert chunks[0].heading_path == "t > X" and chunks[0].tags == ["T1"]
    assert chunks[0].external_url == "https://e/x" and chunks[0].title == "t"
```

- [ ] **Step 2: 确认失败**
- [ ] **Step 3: 最小实现**（合并/切分逻辑照规则直写；硬切按字符数 `max_tokens` 切片兜底）
- [ ] **Step 4: 确认通过** + ruff
- [ ] **Step 5: 提交** `feat: ingest——标题感知分块器`

---

### Task 5: ingest——SourceConnector 与 ObsidianConnector

**Files:**
- Create: `src/ragdb/ingest/connector.py`, `tests/helpers.py`, `tests/test_connector.py`

**Interfaces:**
- Consumes: Task 3 全部 schema；`tests/helpers.make_vault(root: Path) -> Path`（本任务创建）
- Produces:

```python
class SourceConnector(ABC):
    def fetch_all(self) -> list[RawDocument]: ...
    def fetch_changes(self, known: dict[str, FileStamp]) -> ChangeSet: ...
class ObsidianConnector(SourceConnector):
    def __init__(self, vault_path: Path): ...
```

- `tests/helpers.py`：

```python
def make_vault(root: Path) -> Path:
    """创建 6 篇样例笔记：含 frontmatter/wikilink/多级标题/超短/超长边界各一，
    以及 .obsidian/config.json、.trash/x.md、隐藏文件 .hidden.md、attach.png（应全被跳过）。"""
def stamps(vault: Path) -> dict[str, FileStamp]:
    """对 vault 现有 md 计算 known 戳（mtime,size,content_hash），模拟同步过一轮的状态。"""
```

- `fetch_changes` 语义：现盘有而 known 无 → 读内容算 hash：若 hash 命中 known 中**已消失路径**的 hash → `moved`（旧 source_id → 新 RawDocument，旧路径记入已消费集合）；否则 `added`。known 有而现盘无 → `deleted`。双方都有：stamp 三元组相等 → `unchanged+=1`；hash 相同但 stamp 变 → `unchanged+=1`（内容没变，引擎会刷新戳）；hash 不同 → `modified`。`fetch_all` = 全量 RawDocument。跳过规则见 Global Constraints。

- [ ] **Step 1: 失败测试**（用 `make_vault(tmp_path)` + 复制后篡改再跑）

```python
from pathlib import Path
from ragdb.ingest.connector import ObsidianConnector
from tests.helpers import make_vault, stamps

def test_fetch_all_skips_noise(tmp_path: Path):
    vault = make_vault(tmp_path)
    docs = ObsidianConnector(vault).fetch_all()
    ids = {d.source_id for d in docs}
    assert len(ids) == 6
    assert not any(i.startswith((".obsidian", ".trash")) or "/." in f"/{i}" for i in ids)

def test_change_detect_add_modify_delete(tmp_path: Path):
    vault = make_vault(tmp_path)
    conn = ObsidianConnector(vault)
    known = stamps(vault)
    (vault / "新笔记.md").write_text("# 新\n内容", encoding="utf-8")      # added
    p = vault / "笔记1.md"                                                # modified（改内容）
    p.write_text(p.read_text(encoding="utf-8") + "\n追加", encoding="utf-8")
    (vault / "笔记2.md").unlink()                                          # deleted
    cs = conn.fetch_changes(known)
    assert [d.source_id for d in cs.added] == ["新笔记.md"]
    assert cs.modified and cs.modified[0].source_id == "笔记1.md"
    assert cs.deleted == ["笔记2.md"]

def test_move_detected_without_readd(tmp_path: Path):
    vault = make_vault(tmp_path)
    conn = ObsidianConnector(vault)
    known = stamps(vault)
    (vault / "子目录").mkdir()
    (vault / "笔记3.md").rename(vault / "子目录" / "笔记3.md")             # 纯移动
    cs = conn.fetch_changes(known)
    assert len(cs.moved) == 1
    old_id, doc = cs.moved[0]
    assert old_id == "笔记3.md" and doc.source_id == "子目录/笔记3.md"
    assert not cs.added and "笔记3.md" not in cs.deleted

def test_same_hash_still_unchanged(tmp_path: Path):
    vault = make_vault(tmp_path)
    conn = ObsidianConnector(vault)
    known = stamps(vault)
    import os
    os.utime(vault / "笔记1.md", (0, 0))  # 只动 mtime 不动内容
    cs = conn.fetch_changes(known)
    assert not cs.modified and not cs.added
```

- [ ] **Step 2: 确认失败**
- [ ] **Step 3: 最小实现**（`fetch_changes` 两次遍历：先 stat 现盘得 current；deleted=known-current；再对变化文件读内容算 hash 走上述判定；标题取首个 H1 否则 stem）
- [ ] **Step 4: 确认通过** + ruff
- [ ] **Step 5: 提交** `feat: ingest——Obsidian 连接器与增删改移识别`

---

### Task 6: store——SyncState（SQLite）

**Files:**
- Create: `src/ragdb/store/__init__.py`, `src/ragdb/store/state.py`, `tests/test_state.py`

**Interfaces:**
- Produces:

```python
class SyncState:
    def __init__(self, db_path: Path): ...
    def get_all(self) -> dict[str, FileStamp]        # {source_id: (mtime, size, hash)}
    def upsert(self, source_id: str, mtime: float, size: int,
               content_hash: str, chunk_count: int) -> None
    def delete(self, source_id: str) -> None
    def get_meta(self, key: str, default: str | None = None) -> str | None
    def set_meta(self, key: str, value: str) -> None
```

- 表：`files(source_type TEXT DEFAULT 'obsidian', source_id TEXT PRIMARY KEY, mtime REAL, size INTEGER, content_hash TEXT, chunk_count INTEGER, last_indexed_at TEXT)`；`meta(key TEXT PRIMARY KEY, value TEXT)`。连接每次操作即开（`sqlite3.connect(db_path)`），WAL 不必需。

- [ ] **Step 1: 失败测试**（tmp_path 建库，验证 upsert→get_all 往返、覆盖更新、delete、meta）
- [ ] **Step 2: 确认失败**
- [ ] **Step 3: 最小实现**（建表 `CREATE TABLE IF NOT EXISTS`；`get_all` 返回三元组；时间戳 `datetime.now(UTC).isoformat()`）
- [ ] **Step 4: 确认通过** + ruff
- [ ] **Step 5: 提交** `feat: store——SQLite 同步状态库`

---

### Task 7: store——VectorStore（LanceDB）

**Files:**
- Create: `src/ragdb/store/vector_store.py`, `tests/test_vector_store.py`

**Interfaces:**
- Consumes: Task 3 `Chunk`；Task 4 产出的 chunk 列表
- Produces:

```python
@dataclass
class Hit:
    source_id: str; title: str; chunk_index: int; heading_path: str
    content: str; tags: list[str]; vector: np.ndarray | None = None
    score_dense: float = 0.0

class VectorStore:
    def __init__(self, db_dir: Path, dim: int = 1024): ...
    def upsert(self, chunks: list[Chunk], vectors: np.ndarray) -> None
    def delete_by_source(self, source_id: str) -> None
    def fetch_by_source(self, source_id: str) -> list[Hit]   # 按 chunk_index 升序，含 vector
    def search(self, vector: np.ndarray, k: int, *, source_type: str | None = None,
               folder: str | None = None, tags: list[str] | None = None) -> list[Hit]
    def count(self) -> int
```

- 表 `chunks` schema（pyarrow）：`vector: list<float32>(dim)`、`source_type: string`、`source_id: string`、`title: string`、`chunk_index: int32`、`heading_path: string`、`content: string`、`tags: list<string>`、`external_url: string`、`content_hash: string`、`updated_at: timestamp`。`upsert` = 对每个出现的 source_id 先 `delete_by_source` 再 `table.add(rows)`。`search`：SQL where 拼 `source_type = '…'` 与 `source_id LIKE '…/%'`（单引号 `'` 转义为 `''`），`score_dense = 1 / (1 + _distance)`；**tags 过滤在 Python 侧后置**（交集非空才保留），在 docstring 写明。`tags` 列读写用 Python list（LanceDB 支持）。

- [ ] **Step 1: 失败测试**（dim=8 的小向量；构造 Chunk+随机向量验证 upsert→count、覆盖 upsert 不重复、delete、fetch_by_source 有序、search 返回最近邻且 folder/tags/source_type 过滤生效、score_dense∈(0,1]）
- [ ] **Step 2: 确认失败**
- [ ] **Step 3: 最小实现**
- [ ] **Step 4: 确认通过** + ruff
- [ ] **Step 5: 提交** `feat: store——LanceDB 向量库封装`

---

### Task 8: models——协议、真实实现与 ModelHub

**Files:**
- Create: `src/ragdb/models/__init__.py`, `src/ragdb/models/hub.py`, `tests/test_models_protocol.py`, `tests/test_models_real.py`

**Interfaces:**
- Consumes: Task 2 `Settings`（`embed_model/rerank_model/device/dtype/embed_batch`）
- Produces:

```python
class Embedder(Protocol):
    dim: int
    def embed(self, texts: list[str]) -> np.ndarray: ...      # (n, dim) 已 L2 归一化
    def embed_query(self, query: str) -> np.ndarray: ...      # (dim,)
class Reranker(Protocol):
    def rerank(self, query: str, docs: list[str]) -> list[float]: ...
class BGEM3Embedder:   # __init__(model_name, device, dtype, batch_size); 懒加载
class BGEM3Reranker:   # __init__(model_name, device, dtype); 懒加载
class ModelHub:
    def __init__(self, settings: Settings,
                 embedder_factory=None, reranker_factory=None): ...
    @property
    def embedder(self) -> Embedder   # 首次访问构建并缓存
    @property
    def reranker(self) -> Reranker   # 同上（懒加载省 1.2GB 冷启动）
```

- 真实实现要点：`BGEM3FlagModel(model_name, use_fp16=(dtype=="float16"), device=device)`，`encode(texts, batch_size=…, max_length=1024)["dense_vecs"]` 后 L2 归一化；`embed_query` = `embed([q])[0]`。重排 `FlagReranker(model_name, use_fp16=…, device=device)`，`compute_score([[query, d] for d in docs], normalize=True)`。tokenizer 暴露 `BGEM3Embedder.tokenizer` 供 Chunker 默认计数（Task 4 的默认 counter 引用同一懒加载路径即可，不强耦合）。
- **快速测试只测协议与 ModelHub 注入**；真实模型在 `test_models_real.py`（`@pytest.mark.slow` + `RAGDB_SLOW` 未设则 `pytest.skip`）：加载真实 bge-m3，断言 dim==1024、中文相似句对余弦 > 无关句对。

- [ ] **Step 1: 失败测试**（协议符合性：`tests/helpers.py` 的 `FakeEmbedder(dim=8, seed=0)` / `FakeReranker()`（词重叠打分）——**本任务在 helpers 里补这两个类**；ModelHub 用注入工厂验证懒加载只构建一次）

```python
def test_hub_lazy_and_cached():
    calls = []
    def fac(settings):
        calls.append(1); return FakeEmbedder(dim=8)
    hub = ModelHub(Settings.load(path=None), embedder_factory=fac)
    assert not calls                      # 未访问不构建
    _ = hub.embedder; _ = hub.embedder
    assert len(calls) == 1                # 缓存生效
```

- [ ] **Step 2: 确认失败**
- [ ] **Step 3: 最小实现**（Protocol + 两个真实类 + Hub）
- [ ] **Step 4: 确认通过**：`uv run pytest -q -m "not slow"`；`RAGDB_SLOW=1 uv run pytest -q -m slow` 本机手动跑一次并记录结果
- [ ] **Step 5: 提交** `feat: models——嵌入/重排协议、bge 实现与懒加载 ModelHub`

---

### Task 9: sync——SyncEngine

**Files:**
- Create: `src/ragdb/sync/__init__.py`, `src/ragdb/sync/engine.py`, `tests/test_sync_engine.py`

**Interfaces:**
- Consumes: connector/`ChangeSet`、`Embedder` 协议、`VectorStore`、`SyncState`、`Chunker`
- Produces:

```python
@dataclass
class SyncReport:
    added: int = 0; updated: int = 0; deleted: int = 0; moved: int = 0
    failed: list[tuple[str, str]] = field(default_factory=list)  # (source_id, 原因)
    duration: float = 0.0

class SyncEngine:
    def __init__(self, connector, embedder, store, state, chunker): ...
    def run(self, full: bool = False) -> SyncReport
```

- 流程：`full=True` → 清空 store（按 state 全部 source_id 逐个 delete）与 state 后走全量。否则 `fetch_changes(state.get_all())`：added/modified → parse→split→embed→upsert→state.upsert；deleted → store.delete_by_source+state.delete；**moved → 先 `store.fetch_by_source(old)` 取旧向量，删旧 source_id，再以相同向量 upsert 新 chunks（不调 embedder）**，state 删旧写新；单文件异常捕获进 `failed` 继续；`unchanged` 计数不处理。报告 duration 用 `time.perf_counter`。

- [ ] **Step 1: 失败测试**（FakeEmbedder 计数调用次数；make_vault 起步→run 建索引→篡改/删除/移动→再 run 断言四类计数；**移动轮断言 `embedder.embed` 调用次数为 0**；构造损坏文件（如只写 frontmatter 破损文本不会抛错的场景改为 monkeypatch parser 抛错）验证 failed 不中断）

```python
def test_move_does_not_reembed(tmp_path: Path):
    vault = make_vault(tmp_path)
    emb = CountingEmbedder(FakeEmbedder(dim=8))       # 包装器记录 embed 调用
    engine = _engine(vault, emb)
    engine.run()
    (vault / "笔记3.md").rename(vault / "moved.md")
    report = engine.run()
    assert report.moved == 1 and emb.calls == 0
```

- [ ] **Step 2: 确认失败**
- [ ] **Step 3: 最小实现**
- [ ] **Step 4: 确认通过** + ruff
- [ ] **Step 5: 提交** `feat: sync——增量引擎（增删改移四路处理，移动零重嵌入）`

---

### Task 10: retrieve——聚合器

**Files:**
- Create: `src/ragdb/retrieve/__init__.py`, `src/ragdb/retrieve/schema.py`, `src/ragdb/retrieve/aggregator.py`, `tests/test_aggregator.py`

**Interfaces:**
- Consumes: `Hit`、`VectorStore.fetch_by_source`
- Produces:

```python
@dataclass
class SearchResult:
    source_id: str; title: str; heading_path: str; snippets: list[str]
    whole_note: bool; score_rerank: float; score_dense: float; tags: list[str]

def aggregate(ranked: list[tuple[Hit, float]], *, store: VectorStore,
              token_counter: TokenCounter, budget: int = 3000,
              short_note_tokens: int = 600) -> list[SearchResult]
```

- 语义：`ranked` 为重排后按分降序的 (Hit, rerank 分) 列表（已取 top_k）；按 source_id 去重保序（同笔记多命中取最高分）；每笔记：`fetch_by_source` 全块 token 总和 `< short_note_tokens` → 整篇返回（snippets=[全文拼接]，whole_note=True）；否则命中块 index±1 相邻块合并去重为 snippets（whole_note=False）；跨结果按 `budget` 从高分组到低组裁剪（单组自身超预算时截断其 snippets 拼接）。

- [ ] **Step 1: 失败测试**（内存假 store：lambda 字典实现 `fetch_by_source`；覆盖：去重保序、整篇切换、相邻扩展、预算截断）
- [ ] **Step 2: 确认失败**
- [ ] **Step 3: 最小实现**
- [ ] **Step 4: 确认通过** + ruff
- [ ] **Step 5: 提交** `feat: retrieve——small-to-big 聚合器`

---

### Task 11: retrieve——Retriever 与 Core 组装

**Files:**
- Create: `src/ragdb/retrieve/retriever.py`, `src/ragdb/core.py`, `tests/test_retriever.py`, `tests/test_core.py`

**Interfaces:**
- Consumes: Task 8 协议、Task 7 store、Task 10 aggregate
- Produces:

```python
class Retriever:
    def __init__(self, embedder: Embedder, reranker: Reranker, store: VectorStore,
                 token_counter: TokenCounter, *, recall_k: int = 20, top_k: int = 5,
                 token_budget: int = 3000, short_note_tokens: int = 600): ...
    def search(self, query: str, *, top_k: int | None = None, folder: str | None = None,
               tags: list[str] | None = None) -> list[SearchResult]

@dataclass
class Core:      # 全组件装配点；api/mcp/cli 唯一入口
    settings: Settings
    @classmethod
    def from_settings(cls, settings: Settings) -> "Core": ...
    # 懒加载属性：store/state/connector/chunker/hub/embedder/reranker/engine/retriever
```

- `Retriever.search` 管线：`embed_query` → `store.search(vector, recall_k, folder=…, tags=…)` → 空则返回 `[]` → `reranker.rerank(query, [h.content …])` → 降序取 `top_k` → `aggregate`。`Core` 各属性惰性构建并缓存（`functools.cached_property`），chunker 默认计数器在 `device` 环境不可用时回退 `len`（try/except 包裹，警告日志）。

- [ ] **Step 1: 失败测试**（fake 组件注入：断言 recall→rerank→top_k→aggregate 的调用链与参数透传；Core 懒属性构建与缓存）
- [ ] **Step 2: 确认失败**
- [ ] **Step 3: 最小实现**
- [ ] **Step 4: 确认通过** + ruff
- [ ] **Step 5: 提交** `feat: retrieve+core——检索编排与全组件装配点`

---

### Task 12: api——FastAPI（REST + /mcp 挂载 + 同步循环）

**Files:**
- Create: `src/ragdb/api/__init__.py`, `src/ragdb/api/app.py`, `tests/test_api.py`

**Interfaces:**
- Consumes: `Core`（全部经 Core 访问）
- Produces:

```python
def create_app(core: Core) -> FastAPI     # 挂 /mcp；启动时后台同步循环
def run_serve(core: Core) -> None         # uvicorn.run(app, host="127.0.0.1", port=settings.port)
```

- 端点（spec §5.7，路径/方法逐字）：`POST /api/v1/search`、`GET /api/v1/notes?folder=&tag=`、`GET /api/v1/notes/{source_id:path}`、`POST /api/v1/sync`、`GET /api/v1/health`。请求/响应 pydantic 模型；错误统一 `{"error": {"code", "message"}}`（HTTPException handler）；`/mcp` = `mcp_server.build_mcp(core).streamable_http_app()` 挂载；lifespan 启动后台 asyncio task：`while True: engine.run(); await sleep(interval_secs)`（异常捕获记日志不退出）；`get_note` 对不存在路径返回 404 结构化错误。**测试注入 fake Core**（monkeypatch `core.retriever`/`core.engine`/`core.state` 为 fake），不加载模型、不起真服务：TestClient 直测。

- [ ] **Step 1: 失败测试**（五个端点各一测：search 透传参数与结果、notes 列表/详情/404、sync 返回报告、health 字段、错误形状）
- [ ] **Step 2: 确认失败**
- [ ] **Step 3: 最小实现**
- [ ] **Step 4: 确认通过** + ruff
- [ ] **Step 5: 提交** `feat: api——REST 五端点、/mcp 挂载与后台同步循环`

---

### Task 13: mcp_server——stdio 入口与共享工具

**Files:**
- Create: `src/ragdb/mcp_server.py`, `tests/test_mcp_tools.py`

**Interfaces:**
- Consumes: `Core`
- Produces:

```python
def build_mcp(core: Core) -> FastMCP            # 注册 3 个工具
def main() -> None                              # console script ragdb-mcp 入口：build_mcp(Core.from_settings(Settings.load())).run(transport="stdio")
# 工具（MCP 只读，无 sync 工具；工具 docstring 注明只读）：
#   search(query: str, top_k: int = 5, folder: str | None = None, tags: list[str] | None = None) -> str
#   get_note(source_id: str) -> str
#   list_notes(folder: str | None = None, tag: str | None = None) -> str
```

- 返回为人类/模型可读文本：search 每条含 `路径 | 标题链 | 分数` + 片段缩进块；get_note 全文+frontmatter 摘要；list_notes 每行 `路径 | 标题 | tags`。工具实现抽成模块级函数（`_tool_search(core, …)` 等）便于直测。

- [ ] **Step 1: 失败测试**（fake core 直调三个工具函数：断言文本含 source_id/heading_path/分数；get_note 对不存在 id 返回含"未找到"的错误文本而非抛异常；build_mcp 返回对象注册数==3）
- [ ] **Step 2: 确认失败**
- [ ] **Step 3: 最小实现**
- [ ] **Step 4: 确认通过** + ruff
- [ ] **Step 5: 提交** `feat: mcp——stdio 服务器与三只读工具`

---

### Task 14: cli——命令路由、锁协调与端到端

**Files:**
- Create: `src/ragdb/cli.py`, `tests/test_cli.py`, `tests/test_e2e.py`
- Modify: `pyproject.toml`（追加 `[project.scripts] ragdb = "ragdb.cli:main"`、`ragdb-mcp = "ragdb.mcp_server:main"`）

**Interfaces:**
- Consumes: `Core`、`api.app.run_serve`、`mcp_server`
- Produces: `main(argv: list[str] | None = None) -> int`；子命令 `serve | sync | search | rebuild | status`（语义见项目配置清单 §3）；锁协调：`sync/rebuild` 先 GET `http://127.0.0.1:{port}/api/v1/health`（timeout=1s）——serve 存活则 `POST /api/v1/sync` 后打印报告退出；否则 `fcntl.flock(data_dir/ragdb.lock, LOCK_EX | LOCK_NB)` 成功才本地执行，失败提示"serve 进程持有写入权"。

- [ ] **Step 1: 失败测试**（`test_cli.py`：monkeypatch 各动作函数断言路由与参数；httpx 用 respx 或 monkeypatch 断言 serve-alive 转调 / serve-down 走锁两个分支；`test_e2e.py`：fake 组件装配 Core → tmp vault → 直接调 `engine.run()` → `Retriever.search` 断言召回与聚合 → 篡改 vault → run → 结果更新——全链路（connector→chunker→store→retrieve）一镜到底，仍零模型）
- [ ] **Step 2: 确认失败**
- [ ] **Step 3: 最小实现**
- [ ] **Step 4: 确认通过**：`uv run pytest -q -m "not slow"` 全绿 + `uv run ruff check .` 干净
- [ ] **Step 5: 提交** `feat: cli——五子命令、写锁协调与端到端集成测试`

---

## 任务依赖图

```
T1 → T2 → T3 → T4 → T5 ─┐
              └→ T6 ─┐  ├→ T9 → T10 → T11 → T12 → T14
                     └→ T7 ─┘        ↑       └→ T13 ─┘
T2 → T8 ──────────────────────────────┘
（T8 只被 T11 消费；T13 可与 T12 并行派发前的 T11 后任意顺序）
```

## 自审记录（已执行）

1. **规格覆盖**：§5.1→T2、§5.2→T3-5、§5.3→T8、§5.4→T6-7、§5.5→T9、§5.6→T10-11、§5.7→T12、§5.8→T13-14、§6→T9/10/11 各管线步骤、§7→T9(failed)/T12(错误形状)/T14(锁)、§8→各测试+T14 e2e、§10/§11→部署期验证项（实现计划不含）。无缺口。
2. **占位符扫描**：无 TBD/TODO/"适当处理"；所有测试给出真实代码。
3. **类型一致性**：`FileStamp`（含 hash）、`Chunk.title`、`Hit`、`SearchResult`、`SyncReport` 在 T3/T7/T9/T10 间签名一致；`token_counter` 注入贯穿 T4/T10/T11。
