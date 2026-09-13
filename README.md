# ragdb — 个人 RAG 数据库

把知识库变成可语义检索的个人 RAG 服务：本地 BAAI 模型（bge-m3 嵌入 + bge-reranker-v2-m3 重排，MPS GPU），经 **stdio MCP / Streamable HTTP MCP / localhost REST** 三通道供 Claude、OpenClaw、Hermes 等 agent 只读调用。

**多知识源（v1.1）**：`ragdb.toml` 的 `[[sources]]` 可同时接入 Obsidian vault 与若干 GitHub 仓库（公开/私有，token 走环境变量；一期索引 .md 文件），来源前缀化互不冲突，增删来源自动清理孤儿索引。

## 快速开始

```bash
uv sync --extra dev                 # 安装依赖（首次自动下载 Python 3.12 与模型外的常规依赖）
uv run ragdb sync                   # 对 vault 建索引（模型首次下载约 4.5GB，走 hf-mirror）
uv run ragdb search "你的查询"       # 命令行检索
uv run ragdb serve                  # 常驻服务（REST :8770 + /mcp + 30s 后台同步）
```

接入 Claude Code / Desktop（`mcpServers`）：

```json
{ "ragdb": { "command": "uv", "args": ["run", "ragdb-mcp"], "cwd": "<本项目路径>" } }
```

接入 Hermes：`~/.hermes/config.yaml` 的 `mcp_servers` 同上；或指向 `http://127.0.0.1:8770/mcp`。

## 文档

- **智能体接入与操作指南（给其它 agent 用）**：[docs/智能体接入指南.md](docs/智能体接入指南.md)
- 设计规格：[docs/superpowers/specs/2026-09-08-rag-database-design.md](docs/superpowers/specs/2026-09-08-rag-database-design.md)
- 配置说明：[ragdb.toml](ragdb.toml)（全参数带备注）
- 环境事实：[项目配置清单.md](项目配置清单.md)

## 硬约束

vault 全链路**只读**；单写者（serve 持锁）；MCP/HTTP 只读无写工具；v1 不暴露公网。
