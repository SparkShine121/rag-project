# ragdb — 个人 RAG 数据库设计规格

- **日期**：2026-09-08
- **状态**：设计已获用户批准（含 `/mcp` Streamable HTTP 修正案）
- **决策过程**：dev-workflow 阶段一/二完成，Q1-Q13 全部由用户拍板；用户侧决策记录在 Obsidian `自己的项目/RAG项目/技术栈方案.md`

## 1. 背景与目标

为个人知识管理构建一个本地 RAG 数据库：以 Obsidian vault 为知识源，用 BAAI 本地模型做嵌入与重排，把检索能力以 MCP 和 HTTP API 两种形态开放给 Claude Code/Desktop、OpenClaw、Hermes Agent 等多个 agent。

**成功标准**：
1. vault 中任意内容可在 1 秒内（p95，本机）被语义检索并返回带出处的结构化结果；
2. Claude、Hermes Agent（含 CN Desktop）通过 MCP 开箱即用；无 MCP 的 agent 可用 HTTP REST；
3. 笔记增删改移动后 ≤30s 内索引自动跟进，全链路绝不修改用户 vault。

## 2. 需求决策记录（已锁定）

| # | 决策点 | 结论 |
|---|---|---|
| Q1 | 知识源 | 当前 vault `~/Documents/Obsidian Vault`（26 篇 md）；v1 仅 md 文本；预留多渠道与多模态 |
| Q2 | 召回粒度 | 分块嵌入 + 笔记级聚合返回（small-to-big），详见 §7.3 |
| Q3 | 模型运行 | Python 直连（FlagEmbedding + PyTorch MPS）：bge-m3 + bge-reranker-v2-m3 |
| Q4 | 向量库 | LanceDB（嵌入式） |
| Q5 | 同步机制 | 每 30s 定时增量扫描（mtime→hash 两级对比）+ 手动触发；不用 watcher |
| Q6 | 网络边界 | v1 仅 localhost（stdio MCP + 127.0.0.1 HTTP）；公网暴露属 v2 |
| Q7 | MCP 工具集 | 只读三件套：search / get_note / list_notes |
| Q8/Q13 | Python 环境 | uv 管理的 Python 3.12（全机唯一新增解释器），不碰系统 3.9.6 |
| Q12 | 未来渠道 | AI 聊天记录、本地数据文件、代码仓库、微信读书划线（v2，接口已收口） |
| 追加 | MCP 双传输 | FastAPI 同进程挂 `/mcp`（Streamable HTTP），与 stdio 同一套工具 |
| 追加 | Hermes 接入 | 支持 Nous hermes-agent（本机/VPS）与 Hermes Agent CN Desktop；官方文档已核实其 MCP 支持 |

## 3. 范围

**v1 做**：Obsidian 连接器、解析/切块、bge-m3 嵌入、reranker 重排、small-to-big 聚合、LanceDB 存储、SQLite 同步状态、30s 增量同步、stdio MCP + HTTP MCP + REST API、CLI、配置系统、假嵌入器快速测试 + 真实模型慢速测试。

**v1 不做（YAGNI）**：文件监听 watcher、公网暴露/鉴权、任何写操作、图片/PDF/OCR、四个新渠道连接器（仅定义接口）、BM25/稀疏混合检索（bge-m3 稀疏向量与 Lance 混合检索能力预留，v2 零换库启用）、知识图谱（wikilink 数据已存）、Web UI、多用户。

## 4. 架构

```
消费层   Claude Code/Desktop      Hermes Agent/CN Desktop      OpenClaw      任意 agent
              │ stdio                  │ stdio 或 HTTP /mcp        │ stdio      │ HTTP REST
              ▼                        ▼                          ▼            ▼
   ┌──────────────────┐    ┌───────────────────────────────────────────────┐
   │ ragdb-mcp (stdio) │    │ FastAPI 127.0.0.1:8770                        │
   │ FastMCP，按需启动  │    │  REST: /api/v1/*   MCP over HTTP: /mcp        │
   │ 只读              │    │  内含 30s 增量同步循环（serve 进程 = 唯一写者）   │
   └────────┬─────────┘    └───────────────────────┬───────────────────────┘
            └────────────── 进程内直调 ──────────────┘
                                   ▼
   核心库 ragdb（无 IO 副作用之外的依赖方向：api/mcp → core → models/store/ingest）
   ├─ Retriever   embed → 向量召回 → 重排 → 聚合 → token 预算裁剪
   ├─ SyncEngine  扫描 → 差异 → 增删改移 → 写 LanceDB + 状态库 → SyncReport
   ├─ models      Embedder(bge-m3) / Reranker(v2-m3)，懒加载单例，MPS fp16
   ├─ store       VectorStore(LanceDB) + SyncState(SQLite)
   └─ ingest      SourceConnector 抽象 → ObsidianConnector → Parser → Chunker
```

**三条铁律**：
1. **薄壳原则**：`api/` 与 `mcp/` 只做传输与参数校验，业务逻辑零重复；
2. **单写者原则**：仅 `serve` 进程（同步循环）与持文件锁的 CLI sync 可写 LanceDB；MCP/HTTP 读走 Lance 版本化读，读写并发安全；
3. **vault 只读**：全链路任何组件不得写入、移动、删除 vault 内文件。

## 5. 模块规格

包名 `ragdb`，布局 `src/ragdb/`，测试镜像于 `tests/`。

### 5.1 config
- 职责：加载校验 `ragdb.toml` + 环境变量覆盖；提供类型安全 `Settings`。
- 接口：`Settings.load(path: Path | None = None) -> Settings`
- 关键字段默认值：`vault_path=~/Documents/Obsidian Vault`、`data_dir=~/Library/Application Support/ragdb`、`port=8770`、`interval_secs=30`、`recall_k=20`、`top_k=5`、`token_budget=3000`、`chunk{min_chars=100, max_tokens=500, short_note_tokens=600}`、`embed_model=BAAI/bge-m3`、`rerank_model=BAAI/bge-reranker-v2-m3`、`device=mps`、`dtype=float16`（可降级 float32）
- 依赖：pydantic-settings；无其它内部依赖。

### 5.2 ingest
- 职责：连接器抽象 + Obsidian 实现 + md 解析 + 切块。
- 数据模型（全体连接器共用，为 Q12 四渠道收口）：

```python
@dataclass
class RawDocument:
    source_type: str            # "obsidian" | v2: "chat" | "datafile" | "repo" | "weread"
    source_id: str              # vault 内相对路径（obsidian）；其它渠道各自定义
    title: str
    content: str
    metadata: dict              # tags, created, external_url, fetched_at ...
    content_hash: str           # sha256(content)

@dataclass
class Chunk:
    source_id: str
    chunk_index: int            # 0 起
    heading_path: str           # "RAG > 数据管线 > 分块"；无标题时为 title
    content: str
    token_count: int
    tags: list[str]
    external_url: str | None
```

- 接口：
  - `class SourceConnector(ABC)`：`fetch_all() -> Iterable[RawDocument]`、`fetch_changes(known: dict[str, FileStamp]) -> ChangeSet`
  - `FileStamp = tuple[float, int]`（mtime, size）；`ChangeSet` 字段：`added: list[RawDocument]`、`modified: list[RawDocument]`、`moved: list[tuple[str, RawDocument]]`（旧 source_id → 新文档；判定=hash 相同而路径不同）、`deleted: list[str]`（旧 source_id）、`unchanged: int`
  - `class ObsidianConnector(SourceConnector)`：遍历 vault，跳过 `.obsidian/`、`.trash/`、`.` 开头文件与目录、非 `.md` 文件；vault 路径含空格与中文，一律 pathlib。
  - `parse_note(raw) -> ParsedNote`：frontmatter（python-frontmatter）、wikilink 列表（正则 `\[\[([^\]|#]+)`，存入 metadata 供 v2 图谱）、标题树。
  - `class Chunker`：`split(note: ParsedNote) -> list[Chunk]`——按 H2/H3 切；<100 字并入上级；>500 token 按段落二级切；`heading_path` 用 `note.title > H2 > H3` 拼接。
- 依赖：python-frontmatter；config。

### 5.3 models
- 职责：模型加载与推理封装，进程内懒加载单例。
- 接口：
  - `Embedder.embed(texts: list[str]) -> np.ndarray`（fp16 on MPS，batch=32，输出已 L2 归一化）；`Embedder.embed_query(q: str) -> np.ndarray`
  - `Reranker.rerank(query: str, docs: list[str]) -> list[float]`
  - `ModelHub`：持有两个懒加载单例；`Embedder` 在 serve 启动与 sync/search 时加载，`Reranker` 首次 search 才加载。
- 实现要点：FlagEmbedding `BGEM3FlagModel`（`use_fp16=device=="mps"`），tokenizer 同源用于 token 计数；MPS fp16 数值不稳时配置降级 fp32。
- 依赖：FlagEmbedding、torch、numpy；config。

### 5.4 store
- 职责：向量存储与同步状态。
- LanceDB 表 `chunks`（`data_dir/lancedb`）：

| 字段 | 类型 | 说明 |
|---|---|---|
| vector | vector(1024) | bge-m3 稠密向量，L2 归一化 |
| source_type | string | 来源类型 |
| source_id | string | vault 相对路径 |
| title / heading_path / content | string | 血缘与正文 |
| chunk_index | int32 | 块序号 |
| tags | list<string> | frontmatter tags |
| external_url | string | 可空，未来渠道用 |
| content_hash | string | 内容哈希 |
| updated_at | timestamp | 入库时间 |

- 接口：`VectorStore.upsert(chunks, vectors)`（同 source_id 先删后写）、`VectorStore.delete_by_source(source_id)`、`VectorStore.search(vector, k, filter) -> list[Hit]`（filter 支持 source_type/tags）、`VectorStore.count()`
- SQLite `state.db`：表 `files(source_type, source_id, mtime, size, content_hash, chunk_count, last_indexed_at, PRIMARY KEY(source_type, source_id))`；接口 `SyncState.get_all()/upsert()/delete()`；表 `meta(schema_version, last_sync_at)`。
- 依赖：lancedb、sqlite3（标准库）；config。

### 5.5 sync
- 职责：增量引擎。`SyncEngine.run(full: bool = False) -> SyncReport`
- 流程：`fetch_changes` 得到 added/modified/deleted/moved 四类 → 每类走 ingest→models→store 管线 → 更新状态库 → 返回 `SyncReport{added, updated, deleted, moved, failed: list[Path, error], duration}`。
- 关键规则：mtime 未变直接跳过；mtime 变了才算 hash，hash 相同跳过；**hash 相同但路径不同 = moved**，只更新元数据不重嵌入；单文件异常跳过并记入 `failed`，不中断整轮。
- 写者协调：`serve` 进程内定时调用；CLI sync 若检测到 serve 存活（health 探测）则转调 `POST /api/v1/sync`，否则获取 `data_dir/ragdb.lock` 文件锁后自写。
- 依赖：ingest、models、store；config。

### 5.6 retrieve
- 职责：检索编排与聚合。
- 接口：`Retriever.search(query: str, top_k: int = 5, folder: str | None = None, tags: list[str] | None = None) -> list[SearchResult]`。`folder` 过滤语义 = source_id 前缀匹配（如 `Agent技术/` 命中该目录及全部子目录笔记）；`tags` 为交集匹配。
- `SearchResult`：`source_id, title, heading_path, snippets: list[str]（命中+扩展）, whole_note: bool, score_rerank: float, score_dense: float, tags`
- 管线：query 嵌入 → `VectorStore.search(recall_k=20)` → Reranker 对候选重排 → 取 top_k 块 → 按 source_id 分组：同笔记命中≥1 块时拉取其相邻块（chunk_index±1）拼合；笔记全文 <600 token 则整篇返回（`whole_note=True`）→ 按 `token_budget=3000` 从高分到低分裁剪。
- 依赖：models、store；config。

### 5.7 api（HTTP 薄壳）
- 职责：FastAPI 应用，仅校验与转发；同进程挂 `/mcp`。
- 端点：
  - `POST /api/v1/search` `{query, top_k?, folder?, tags?}` → `list[SearchResult]`
  - `GET /api/v1/notes?folder=&tag=` → `[{source_id, title, tags}]`（不含正文）
  - `GET /api/v1/notes/{source_id:path}` → 全文 + frontmatter
  - `POST /api/v1/sync` → `SyncReport`
  - `GET /api/v1/health` → `{status, db_ok, models_loaded, note_count, last_sync_at}`
  - `/mcp`：FastMCP streamable HTTP app，挂载于同一 ASGI 应用
- 仅绑 `127.0.0.1`；错误统一 `{"error": {"code", "message"}}`。
- 依赖：fastapi、uvicorn、mcp；retrieve/sync。

### 5.8 mcp + cli（另两个薄壳）
- `ragdb-mcp`（console_script）：FastMCP stdio 入口，暴露与 `/mcp` 完全相同的 3 个工具；**只读**——MCP 侧不提供 sync 触发（避免多写者），工具描述中注明。
- 工具签名：
  - `search(query: str, top_k: int = 5, folder: str | None = None, tags: list[str] | None = None) -> str`（结构化文本，含来源路径/标题链/片段/分数）
  - `get_note(source_id: str) -> str`（全文+元数据）
  - `list_notes(folder: str | None = None, tag: str | None = None) -> str`
- CLI（argparse）：`ragdb serve | sync | search "query" [--top-k N] | rebuild | status`
- 依赖：mcp；retrieve。

## 6. 数据流（三条管线）

**初始建索引 / 全量重建**：`fetch_all` → parse → chunk → 批量 embed（batch 32）→ upsert → 状态库全量刷新。26 篇秒级；速率按 >50 chunks/s（MPS）估，几千篇分钟级。

**增量同步（每 30s + 手动）**：§5.5 流程。典型延迟 ≤30s + 单文件处理 <1s。

**查询**：嵌入 ~30ms → 向量检索 ~20ms → 重排 20 候选 ~200-400ms → 聚合 <10ms；端到端 <1s (p95)。

## 7. 错误处理

| 场景 | 行为 |
|---|---|
| 单文件解析/嵌入失败 | 跳过，记 `SyncReport.failed`，日志含原因，不中断 |
| 模型加载失败 | serve 启动失败并给明确指引（检查模型目录/HF 镜像）；检索时降级报结构化错误 |
| LanceDB 写冲突 | 文件锁 + 单写者原则杜绝；MCP/HTTP 只读天然安全 |
| vault 路径不存在/为空 | 配置校验阶段直接报错，不启动 |
| 空查询/超预算参数 | 422 结构化错误；MCP 侧返回说明文本 |
| 全量重建中断 | 状态库按 source_id 粒度更新，重跑幂等续传 |

## 8. 测试策略

- **假嵌入器**：`FakeEmbedder` 用确定性哈希生成 1024 维归一化向量，驱动全部快速测试（无模型下载，毫秒级）；`FakeReranker` 按词重叠打分。
- **fixture vault**：`tests/fixtures/vault/` 放 6 篇样例笔记（含 frontmatter、wikilink、多级标题、超长/超短边界样例）。
- **覆盖场景**：切块规则（H2/H3、过短并入、超长二切）、解析（frontmatter/wikilink）、同步四场景（增/改/删/移）、移动不重嵌入、删除清孤儿、检索管线端到端、token 预算裁剪、API 合同、MCP 工具合同、锁协调（serve 在跑时 CLI 转调）。
- **慢速真实测试**：`@pytest.mark.slow` + `RAGDB_SLOW=1` 门控——真实 bge-m3/reranker 加载、中文查询召回质量断言（fixture 中放语义相近/无关笔记对，断言相关者排前）。
- **TDD**：dev-workflow 阶段四纪律，每模块先失败测试后实现。

## 9. 性能与资源预算

| 项 | 预算 |
|---|---|
| 检索延迟 | <1s p95（本机，含重排） |
| 稳态内存 | ~4GB（两模型 fp16 + torch 运行时；Reranker 懒加载省 1.2GB 冷启动） |
| 磁盘 | 模型 ~2.4GB + 依赖 ~1.5GB + 解释器 70MB + 向量数据 <50MB ≈ **<5GB** |
| 同步周期开销 | 空扫描（无变更）<0.5s，每 30s 一次 |

## 10. 外部 agent 接入矩阵

| 消费端 | 传输 | 接入方式 | 依据 |
|---|---|---|---|
| Claude Code/Desktop | stdio MCP | `mcpServers` 配 `uv run ragdb-mcp` | MCP 标准 |
| Hermes Agent（Nous，本机） | stdio MCP | `~/.hermes/config.yaml` `mcp_servers.ragdb` 同上配置；或 `hermes import-agent claude-code` 直接迁移 | 官方文档已核实（2026-09-08） |
| Hermes Agent CN Desktop | stdio MCP | 同上（同一套 config） | 同上 |
| Hermes Agent（VPS/远程） | HTTP MCP | 指向 `http://<mac>:8770/mcp`，需 v2 公网暴露+鉴权后可用 | 官方文档已核实支持 remote HTTP MCP |
| OpenClaw | stdio / HTTP MCP / REST | `openclaw mcp add ragdb --command uv --arg run --arg ragdb-mcp`（stdio）；或 `openclaw mcp add ragdb --url http://127.0.0.1:8770/mcp --transport streamable-http`；Control UI/CLI/config 三处均可添加 | 官方文档已核实（2026-09-08） |
| 任意 HTTP agent | REST | OpenAPI 规范，函数调用直接映射 | v1 原生 |

## 11. 风险与对策

| 风险 | 对策 |
|---|---|
| MPS fp16 数值不稳 | 配置项 `dtype` 可降 float32，测试覆盖两种模式（slow） |
| HF 下载不稳定 | `HF_ENDPOINT=https://hf-mirror.com` 镜像；模型只下载一次到固定目录 |
| LanceDB API 变更 | 锁定次要版本（pyproject `~=`）；store 层封装隔离，表 schema 单一变更点 |
| vault 大目录扫描变慢 | mtime 一级过滤；实测 >5000 篇再优化（分桶/快照） |
| 多 agent 并发读 | Lance 版本化读；单写者原则；MCP 只读 |

## 12. v2 展望（不在本期实现）

四渠道连接器（聊天记录/数据文件/代码仓库/微信读书划线）、bge-m3 稀疏向量 + Lance FTS 混合检索、图片/PDF 多模态、watcher 实时监听、公网暴露（隧道+API key+限流）、MCP 写工具（追加笔记/打标签，需冲突策略）、wikilink 知识图谱。
