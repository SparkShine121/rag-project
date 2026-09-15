# ragdb v1.3.1 MCP 进程模型空闲卸载 Implementation Plan

> **For agentic workers:** dev-workflow 阶段四（内联 TDD）执行。checkbox 跟踪。

**Goal:** `ragdb-mcp`（agent 拉起的 stdio 进程）接入与 serve 相同的 TTL 空闲卸载——空闲超 `unload_idle_secs` 释放模型权重（进程保持存活，**绝不退出**——stdio 连接断开会破坏 agent 会话），下次 search 自动重载。

**Architecture:** `mcp_server.start_idle_unloader(core, interval_secs=60)`：守护线程循环调用 `core.hub.maybe_unload()`（v1.3 已有机制，零新逻辑）；`main()` 在构建 core 后启动（daemon 线程）。复用 `unload_idle_secs` 配置，零新增旋钮。

## Global Constraints

- 继承全部既有约束。**进程绝不自行退出**（仅 release 权重）。
- 巡检异常必须捕获记日志（守护线程崩溃 = 静默失效）。
- 真实冒烟：脚本化 stdio MCP 会话（initialize → tools/call search）+ TTL 到期 footprint 对比。

---

### Task 1: start_idle_unloader

**Files:** Modify `src/ragdb/mcp_server.py`、`tests/test_mcp_idle_unloader.py`
**Produces:** `start_idle_unloader(core, interval_secs=60) -> tuple[threading.Thread, threading.Event]`（daemon 线程 + stop 事件；循环 `stop.wait(interval)` → `core.hub.maybe_unload()`，异常捕获记 WARNING）。
- [ ] RED（巡检触发 spy、ttl=0 时 maybe_unload 自行 no-op、stop 事件结束线程、巡检异常不杀线程）→ GREEN → 提交

### Task 2: main 接线 + 文档

**Files:** Modify `src/ragdb/mcp_server.py`（main 启动 watcher）、`ragdb.toml`（unload_idle_secs 注释补 MCP 进程语义）、`docs/智能体接入指南.md`（内存行为补 MCP 进程行）、Obsidian；Tests：main 薄不直测（thin wrapper），以 T1 覆盖
- [ ] 接线 + 文档 → 全量回归 → 提交

### Task 3: 真实 stdio 冒烟

脚本驱动 `ragdb-mcp-launcher.sh`（stdin 发 initialize/initialized/tools-call search）→ 进程 footprint（加载态）→ 空闲超 TTL → footprint（卸载态）→ 再 search（重载）。数据入汇报。
- [ ] 实测对比
