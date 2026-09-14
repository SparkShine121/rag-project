# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目定位

个人 RAG 数据库（ragdb v0.1.0）：Obsidian 知识库向量化检索，经 stdio MCP + Streamable HTTP MCP + localhost REST 三通道供 Claude/OpenClaw/Hermes 等多 agent 只读调用。

## 常用命令

（与 README「快速开始」为同一事实的两面：改其一必须同步另一处）

```bash
uv sync --extra dev                  # 装依赖（Python 3.12 由 uv 管理）
uv run pytest                        # 全量快速测试（约 8s，零模型零网络）
RAGDB_SLOW=1 uv run pytest -m slow   # 真实模型慢速测试（需模型已下载）
uv run ruff check .                  # Lint
uv run ragdb sync|search|serve|rebuild|status   # CLI（serve 常驻 = FastAPI + 30s 同步循环）
uv run ragdb-mcp                     # stdio MCP 服务器（Claude 配置指向这里）
```

## 架构一分钟版

- **薄壳原则**：`api/`（REST+`/mcp` 挂载）、`mcp_server.py`（stdio）、`cli.py` 三壳共享核心库；装配点 `core.py`（cached_property 惰性构建）。
- **核心链**：`ingest`（ObsidianConnector→Parser→Chunker）→ `sync`（mtime→hash 两级增量，移动零重嵌入）→ `store`（LanceDB 向量 + SQLite 状态）→ `retrieve`（召回→rerank_top_k 精排→small-to-big 聚合）。
- **三条铁律**：vault 全链路只读；单写者（serve 进程持 `ragdb.lock`，CLI 撞锁拒绝）；MCP/HTTP 只读无写工具。
- **配置**：`ragdb.toml`（全参数带备注，改动需 rebuild 的项已标注）+ `RAGDB_*` 环境变量覆盖；数据在 `~/Library/Application Support/ragdb/`。
- **性能基线**（M4 实测）：rerank_top_k=5 时热查询 0.7-1.2s；模型必须显式传 `devices=["mps"]`（FlagEmbedding 自动探测只认 CUDA）。

## 关键文档

- 设计规格（接口/常量唯一权威）：`docs/superpowers/specs/2026-09-08-rag-database-design.md`
- 实现计划（14 任务 + 测试代码）：`docs/superpowers/plans/2026-09-08-ragdb-implementation.md`
- 环境事实与已知坑：`项目配置清单.md`；错题集：`errors_file/errors.md`

## 开发流程约束

本项目安装了项目级 skill：`.claude/skills/dev-workflow/`。凡在本项目进行功能开发、bug 修复、代码维护等编码任务，必须按该 skill 定义的六阶段闭环流程执行（需求拷问 → 设计探索 → 计划拆分 → TDD 实现 → 收尾整理 → 自进化）。

## 证据先于断言（强化，用户 2026-09-08 指定）

- 任何"完成/通过/修复"声明前，必须有**本回合新鲜运行**的验证命令及输出。
- 测试/构建/lint 命令一律先 `set -o pipefail`，禁止让管道尾命令（`| tail` 等）掩盖退出码；pipefail 链内禁用 `| head`（SIGPIPE 误报）。
- GREEN 验证与提交必须在同一 `&&` 命令链内完成，链中任何一步失败即停止，不得带病提交。
- 提交前 `git status --short` 确认无未跟踪的实现文件残留——**新增实现文件与其测试同笔提交**。
- 源码/文本修改一律使用 Edit/Write 工具（不命中即报错），**禁用 replace 脚本静默替换**（已三犯）；确需脚本批量修改必须带后置断言（读取目标位置验证新串存在，否则非零退出）。
- 合并修复分支后必须重跑该修复对应的测试集（GREEN 才允许 push）；关键装配点（如 hub 参数传递）有常驻测试覆盖，防止合并丢失。
- 冒烟/重启前标准化三步：① pkill -9 + pgrep 确认无旧进程残留；② 断言 health 启动标识等于本轮值；③ 再跑用例。
