# ragdb v1.3.2 serve 空闲自杀（supervised exit）Implementation Plan

> **For agentic workers:** dev-workflow 阶段四（内联 TDD）执行。checkbox 跟踪。

**Goal:** serve 在有监督（launchd KeepAlive）运行时，模型空闲超 TTL 后**整进程退出**（替代 v1.3 的仅卸载权重），launchd 秒级拉起全新空进程——空闲内存从卸载态 ~1.4GB 降至基线 ~250MB；agent（HTTP MCP/REST）下次调用透明重连（2026-09-16 Hermes 实测通过：杀 serve → launchd 重启 → 再 search 成功且结果一致，agent 零感知）。

**Background（实测证据）:**
- 加载态 footprint 4864MB → TTL 卸载态 862MB（权重已释放但库驻留+分配器残留）→ **进程退出后 launchd 重启的新进程 ~250MB**。
- Hermes CN runtime 0.19.0-cn.7 的 stdio MCP 因 watchdog 打包问题全废，现役通道为 HTTP MCP（`config.yaml mcp_servers.ragdb → 127.0.0.1:8770/mcp`）；重连实测走 HTTP 通道。
- 代价与现状 TTL 卸载完全相同：下次检索付一次冷加载（~15-20s）。

**Architecture:** `api/app.py` 的 30s 巡检点（`app.py:91` 现调用 `maybe_unload`）扩展三态判定：**无监督**（默认，终端直跑）→ 维持 v1.3 卸载行为；**有监督**（环境变量 `RAGDB_SUPERVISED=1`，由 LaunchAgent plist 注入）且空闲超 TTL 且无在飞检索 → `os._exit(0)`，launchd 立即重启。ragdb-mcp（stdio）**不变**——进程绝不退出（v1.3.1 契约）。

## Global Constraints

- **退出仅发生在 supervised 模式**：裸终端跑 `ragdb serve` 永不自杀（无人拉起会变成服务中断），回落到 v1.3 卸载行为。
- **有在飞检索时绝不退出**（该次调用会失败——重连只保下次调用，不保进行中的调用）。
- 用 `os._exit(0)` 硬退出：SIGTERM 优雅关闭有已知挂起问题（项目配置清单 v1.3.1 待办）；fcntl 文件锁随进程死亡自动释放；SQLite 崩溃安全。
- 退出频率天然有界：TTL（默认 1800s）内最多一次；模型从未加载（idle=None）时不退出（已是目标内存，避免无谓重启churn）。
- 零新增用户配置旋钮：TTL 复用 `unload_idle_secs`；supervised 是部署态标志（plist 注入），非用户参数。

---

### Task 1: 判定函数 + serve 循环接线

**Files:** Modify `src/ragdb/api/app.py`、`tests/test_serve_idle_exit.py`（新建）
**Produces:**
- 纯函数 `idle_exit_due(idle: float | None, ttl: int, supervised: bool, inflight: int) -> bool`：
  `supervised` 为假 → False；`inflight > 0` → False；`idle is None` → False；否则 `idle > ttl`。
- `search` 端点包在飞计数器（`app.state.search_inflight`，try/finally 增减）。
- `loop()` 巡检点接线：supervised 且 `idle_exit_due(...)` → 记 WARNING 日志 → `os._exit(0)`；否则维持 `maybe_unload()`（v1.3 行为不变）。
- 测试覆盖：四条判定边界（supervised 门、在飞门、None 门、TTL 边界 = 不含等号）；接线以 T3 真实冒烟验证（thin wrapper 不直测，沿 v1.3.1 先例）。
- [ ] RED → GREEN → 提交

### Task 2: 部署与文档

**Files:** Modify `~/Library/LaunchAgents/com.ragdb.serve.plist`（EnvironmentVariables 增加 `RAGDB_SUPERVISED=1`）、`ragdb.toml`（unload_idle_secs 注释补三态语义）、`docs/智能体接入指南.md`（内存行为节：supervised 退出语义 + agent 无感重连）、`README.md`（版本表 v0.1.3.2 行）、`项目配置清单.md`（坑：裸跑 serve 不自杀；SIGTERM 挂起待办与 _exit 的关系）
- [ ] plist + 文档 → 全量回归 → 提交

### Task 3: 真实冒烟（supervised）

标准化三步（pkill -9 + health 启动标识 + 用例）。临时以 `RAGDB_UNLOAD_IDLE_SECS=15` 覆盖：launchd 重启 serve（断言新 pid）→ search（加载态 footprint ~4.8GB）→ 空闲 80s（TTL 15s + 巡检 30s）→ **断言旧 pid 已死、新 pid 存在** → footprint ~250MB → 再 search（冷加载 ~15-20s，结果可用）。数据入汇报。
- [ ] 实测对比（退出/重启/重连三断言）
