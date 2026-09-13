# ragdb v1.2 多类型内容（代码/PDF/OCR）Implementation Plan

> **For agentic workers:** dev-workflow 阶段四（内联 TDD）逐任务执行。checkbox 跟踪。

**Goal:** 知识源从 md 扩展为多类型：代码文件（启发式切块）、PDF（PyMuPDF 按页切块 + Apple Vision OCR 回退）、folder 来源类型、扩展名白名单与数量/大小上限。

**Architecture:** 新增 `ingest/pipeline.py: chunk_document(doc, ...)` 解析分发器（引擎不再直接持有 Chunker）；`CodeChunker`（顶级定义对齐 + 行窗口兜底）；`PdfParser`（PyMuPDF 逐页，无文本层 → OCR 回退 → 仍无 → failed）；`FolderConnector`（type="folder" 本地多类型目录）；RawDocument 增加 `binary: bytes | None`（二进制不进 content）；GitHub 连接器 .md-only → 白名单全量（PDF 走 base64 → binary）。

**Tech Stack:** + pymupdf（AGPL，个人使用已确认）、pyobjc-framework-Vision（Apple Vision OCR，macOS 系统框架）。

## Global Constraints

- 继承 v1.1 全部约束（pipefail 链控、实现与测试同笔提交、每任务 feature 分支、MockTransport/程序化 fixture 零真实网络）。
- 上限：`max_file_mb=50`、`max_files_per_source=5000`（达到上限在 SyncReport 明确提示，不静默截断）；扫描版/超限文件一律进 failed，绝不静默。
- obsidian 类型保持 md-only；白名单默认 18 项（用户已确认）。
- OCR：`ingest/ocr.py` 隔离 pyobjc 依赖（import 探测，未安装时优雅降级）；PdfParser 接受 `ocr_fn` 注入（测试不真跑 Vision）；真实 OCR 冒烟标 slow。

---

### Task 1: 过滤配置

**Files:** Modify `src/ragdb/config.py`、`ragdb.toml`、`tests/test_config.py`
**Produces:** `IngestConfig(include_exts=[18 项默认], max_file_mb=50, max_files_per_source=5000, exclude_dirs=[".git","node_modules","dist","build","__pycache__",".venv","venv"])`；`Settings.ingest`；`SourceConfig.include_exts/max_file_mb=None`（None=用全局）；`Settings.effective_ingest(source)` 合并函数。
- [ ] RED（默认值、per-source 覆盖、toml 解析）→ GREEN → 提交

### Task 2: CodeChunker

**Files:** Create `src/ragdb/ingest/code.py`、`tests/test_code_chunker.py`
**Produces:** `CodeChunker(token_counter).split(doc: RawDocument) -> list[Chunk]`：按扩展名识别语言；正则识别顶级定义（python `^(def|class)`、js/ts `function|const|class`、go `func`）为切块边界；符号名进 heading_path（`utils.py > def parse_args`）；无定义的小文件整文件一块；超长按行窗口兜底（≤chunk.max_tokens）。
- [ ] RED（python 函数/类边界、符号名进标题链、无定义整块、行窗口兜底、非代码扩展名直读）→ GREEN → 提交

### Task 3: PDF 管线 + OCR 回退

**Files:** Create `src/ragdb/ingest/pdf.py`、`src/ragdb/ingest/ocr.py`；Modify `pyproject.toml`（pymupdf、pyobjc-framework-Vision）；Tests `tests/test_pdf.py`
**Produces:** `PdfParser(ocr_fn=None).split(doc) -> list[Chunk]`：PyMuPDF 从 binary/memory 打开 → 逐页 get_text() → 每页一块（heading_path=`x.pdf > 第 N 页`）；页无文本且 ocr_fn 可用 → ocr_fn(png_bytes) 回退；页仍无文本且无 OCR → 整文件 failed（"疑似扫描版"）；`ocr.available()` import 探测；`ocr.recognize_png(png_bytes, langs)` Apple Vision 实现（slow 冒烟）。
- [ ] RED（文本层 PDF 按页、页码标题链、无文本层+fake ocr 回退、无 ocr → raise 疑似扫描版、空 PDF）→ GREEN → 提交

### Task 4: 解析分发器 pipeline

**Files:** Create `src/ragdb/ingest/pipeline.py`；Modify `src/ragdb/sync/engine.py`（chunker → pipeline.chunk_document）；Tests `tests/test_pipeline.py`
**Produces:** `chunk_document(doc, chunker, pdf_parser, code_chunker) -> list[Chunk]`：按 source_type+扩展名分发（.md→Chunker / .pdf→PdfParser / 白名单代码→CodeChunker / 未知→内容直读单块）；RawDocument 增加 `binary: bytes | None = None`。
- [ ] RED（三类分发、未知扩展直读、binary 不进 content）→ GREEN → 提交

### Task 5: FolderConnector

**Files:** Create `src/ragdb/ingest/folder.py`；Modify `src/ragdb/ingest/factory.py`（type 分发）；Tests `tests/test_folder_connector.py`
**Produces:** `FolderConnector(source, ingest_cfg)`：walk 白名单扩展、跳过 exclude_dirs/隐藏项/超限文件（failed 提示）、文件数上限（SyncReport 提示）；FileStamp 语义同 obsidian。
- [ ] RED（白名单遍历、排除目录、超限 failed、上限提示）→ GREEN → 提交

### Task 6: GitHub 白名单扩展

**Files:** Modify `src/ragdb/ingest/github.py`；Tests `tests/test_github_connector.py` 追加
**Produces:** `_md_blobs` → `_matching_blobs(include_exts)`；PDF/代码走 contents base64 → binary；超限不下载直接 failed。
- [ ] RED（pdf 拉取进 binary、白名单过滤、超限跳过）→ GREEN → 提交

### Task 7: 端到端 + 文档 + 真实冒烟

**Files:** Tests `tests/test_v12_e2e.py`；Modify `ragdb.toml`、`docs/智能体接入指南.md`、README、Obsidian 笔记
- [ ] e2e：folder 源（md+code+pdf 混合 fixture，PDF 程序化生成）+ github 源（mock）三类型检索；真实冒烟（含 PDF 的公开仓库）
- [ ] RED → GREEN → 全量回归 → 文档提交
