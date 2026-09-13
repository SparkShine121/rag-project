# ragdb v1.1 多源接入（obsidian + GitHub）Implementation Plan

> **For agentic workers:** 用 dev-workflow 阶段四（内联 TDD）逐任务执行。checkbox 跟踪。

**Goal:** 知识源从单一 Obsidian vault 扩展为可配置多源（obsidian + N 个 GitHub 仓库，可随时增删改），source_id 全局前缀化，GitHub 走 Contents API + blob-sha 增量。第一期仅索引 .md；代码/PDF 管线属第二期。

**Architecture:** 新增 `MultiSourceConnector`（聚合 N 个 `SourceConnector` 子连接器并做 source_id 前缀化与跨源变更归并）；`GitHubConnector` 用 git blob sha 直接作 content_hash（树比对零下载判变更）；引擎按来源前缀清除孤儿状态（来源改名/删除/升级迁移自动收敛，无需手动 rebuild）。

**Tech Stack:** 现有栈 + httpx MockTransport（测试）。

## Global Constraints

- 全部继承 v1.0 计划的 Global Constraints（pipefail 链控、实现与测试同笔提交、每任务 feature 分支）。
- RawDocument 新增 `hash_override: str | None = None`，`content_hash` 属性优先返回 override（GitHub 用 blob sha，语义仍是"内容相同 ⇔ hash 相同"）。
- GitHub API base `https://api.github.com`；token 走 Bearer；第一期只收 `.md`。
- 私有仓库：`token_env` 指定的环境变量缺失 → 装配时明确报错不启动。
- 测试一律 MockTransport/假连接器，禁止真打 GitHub API（真实 API 冒烟单独做）。

---

### Task 1: SourceConfig 多源配置

**Files:** Modify `src/ragdb/config.py`、`tests/test_config.py`
**Produces:** `SourceConfig(name, type: Literal["obsidian","github"]="obsidian", path=None, repo=None, ref="main", token_env=None)`；`Settings.sources: list[SourceConfig]`；`Settings.effective_sources()`（sources 空时回退 `[{name:"obsidian", type:"obsidian", path:vault_path}]`）；校验：name 唯一、github 须有 repo、obsidian 须有 path。

- [ ] RED：默认回退、[[sources]] 解析、重名报错、github 缺 repo 报错、obsidian 缺 path 报错
- [ ] GREEN：`load()` 中 `data["sources"] = [SourceConfig(**s) for s in ...]`；`effective_sources` 方法 + validator

### Task 2: RawDocument.hash_override + MultiSourceConnector

**Files:** Modify `src/ragdb/ingest/schema.py`；Create `src/ragdb/ingest/multi.py`；Create `tests/test_multi_connector.py`
**Produces:**

```python
# schema.py: RawDocument 增加 hash_override 字段；content_hash 属性 = override or sha256
class MultiSourceConnector(SourceConnector):
    def __init__(self, items: list[tuple[SourceConfig, SourceConnector]])
    @property
    def source_prefixes(self) -> list[str]   # ["obsidian/", "myrepo/"]
    def fetch_all(self) -> list[RawDocument]          # 子文档 source_id 加前缀
    def fetch_changes(self, known) -> ChangeSet       # 按前缀拆分下发，结果前缀化归并；
                                                      # known 中无主前缀 → 整体 deleted
```

共享 diff 归并逻辑抽为 `ingest/changeset.py: build_change_set(known, current, fetch_doc)`（Task 3 中 ObsidianConnector 重构复用）。
- [ ] RED：前缀化 fetch_all；known 前缀路由；无主前缀整体删除；move 前缀化；source_prefixes
- [ ] GREEN

### Task 3: GitHubConnector + ObsidianConnector 重构复用

**Files:** Create `src/ragdb/ingest/github.py`；Modify `src/ragdb/ingest/connector.py`（用 build_change_set）；Tests `tests/test_github_connector.py`（httpx.MockTransport）+ 既有 connector 测试保持绿
**Produces:**

```python
class GitHubConnector(SourceConnector):
    def __init__(self, source: SourceConfig, token: str | None = None,
                 client: httpx.Client | None = None)
    def fetch_all(self) -> list[RawDocument]
    def fetch_changes(self, known) -> ChangeSet   # tree blob-sha 比对；仅变更文件走 contents
```

行为：只收 `.md` blob；`hash_override=blob_sha`、metadata 含 `blob_sha/html_url`；unchanged 文件零下载；私仓无 token 报错。ObsidianConnector 行为不变（回归靠既有 18 个测试）。
- [ ] RED（tree 过滤/鉴权头/base64 解码/变更四类/unchanged 零下载/无 token 错误）
- [ ] GREEN

### Task 4: 装配与孤儿前缀清除

**Files:** Create `src/ragdb/ingest/factory.py`（`build_connectors(settings)`）；Modify `src/ragdb/core.py`（connector=MultiSourceConnector）、`src/ragdb/sync/engine.py`（run 开头按 `connector.source_prefixes` 清除无主 state/store 行，计入 deleted）；Tests `tests/test_factory.py`、`tests/test_sync_engine.py` 补孤儿清除用例
**行为：** obsidian→ObsidianConnector(expanduser path)；github→token=`os.environ.get(token_env)`（token_env 指定但缺失→ValueError）；无主前缀清除使来源改名/删除/升级免 rebuild。
- [ ] RED（工厂类型分发、token 缺失错误、孤儿清除且计入 deleted）
- [ ] GREEN（全量回归）

### Task 5: 双源端到端

**Files:** Create `tests/test_multi_e2e.py`
- [ ] 场景：obsidian 源（make_vault）+ fake github 源（预设 md 文档）→ engine.run 全量 → source_id 带前缀入库；检索结果带前缀；修改 github 源文档 → 增量只动该源；删除 github 源配置 → 下轮全量 deleted（孤儿清除）；`ragdb rebuild` 幂等。
- [ ] RED → GREEN → 全量回归

### Task 6: 文档与配置备注更新

**Files:** Modify `ragdb.toml`（[[sources]] 示例块 + 备注）、`docs/智能体接入指南.md`（source_id 前缀、folder 跨源、来源变更自动收敛说明）、README、Obsidian 技术栈方案（v1.1 进展）
- [ ] 内容更新 + 提交
