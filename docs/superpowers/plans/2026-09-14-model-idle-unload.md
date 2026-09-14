# ragdb v1.3 模型空闲卸载（TTL）Implementation Plan

> **For agentic workers:** dev-workflow 阶段四（内联 TDD）执行。checkbox 跟踪。

**Goal:** serve 常驻时，模型权重在空闲超过 TTL 后自动释放（实测 footprint ~5.0GB → 目标回落至 ~1.5GB 以下），再次检索自动重载（付 ~15s 冷加载）。解决"个人 agent 查询稀疏、5GB 常驻浪费"问题。

**Architecture:** 权重释放走 **wrapper 内部重置**（BGEM3Embedder/Reranker 新增 `release()`：`self._model = None` + `torch.mps.empty_cache()`）——Retriever/Engine 持有的 wrapper 引用不受影响，下次访问 `.model` 属性自动从 HF 缓存重载。ModelHub 增加 last-used 时间戳与 `maybe_unload()`；serve 同步循环每轮调用。**不做对象级驱逐**（Retriever 持有 wrapper 引用会使对象驱逐失效——设计关键决策）。

**Tech Stack:** 现有栈；`torch.mps.empty_cache()`（MPS 可用时）+ `gc.collect()`。

## Global Constraints

- 继承全部既有约束。新配置 `unload_idle_secs: int = 1800`（0 = 永不卸载，保持驻留）。
- 卸载只释放**权重**，不销毁 wrapper 对象（依赖注入引用安全）；in-flight 调用安全（调用开始时已取局部引用）。
- 卸载动作必须 try/except 包裹（清理失败只记日志，不允许拖垮 serve 循环）。

---

### Task 1: ModelHub TTL 机制

**Files:** Modify `src/ragdb/config.py`（unload_idle_secs）、`src/ragdb/models/hub.py`（release/maybe_unload/last_used）、`tests/helpers.py`（Fake 模型补 release 计数）、`tests/test_models_protocol.py` 或新文件 `tests/test_model_hub_ttl.py`
**Produces:** `Settings.unload_idle_secs=1800`；`BGEM3Embedder.release()/BGEM3Reranker.release()`（`_model=None` + MPS cache 清理，幂等）；`ModelHub(settings, ..., clock=time.monotonic)`：`embed/embed_query/rerank` 调用刷新 `_last_used`；`release()` 幂等释放两模型权重；`maybe_unload(now=None) -> bool`（ttl>0 且已加载且空闲>ttl → release）。
- [ ] RED：默认配置值；embed 后 last_used 刷新；ttl=0 不卸载；超时后 unload → fake 模型 release 被调 + weights 置空；再次访问 .model 重建（懒重载路径）；release 幂等
- [ ] GREEN → 提交

### Task 2: serve 循环接线 + 文档

**Files:** Modify `src/ragdb/api/app.py`（同步循环每轮 `hub.maybe_unload()`）、`src/ragdb/core.py`（hub 构造传 ttl/clock）、`ragdb.toml`（新参数备注）、`docs/智能体接入指南.md`（内存行为说明）、Obsidian 技术栈方案；Tests `tests/test_api.py` 补接线用例（monkeypatch spy）
- [ ] RED：serve 循环调用 maybe_unload（spy）；Core.hub 携带 ttl → GREEN → 全量回归 → 提交

### Task 3: 真实冒烟（手动证据）

启动真实 serve（unload_idle_secs=30 临时值）→ 检索（模型加载，footprint 记录）→ 等待 35s → footprint（应显著回落）→ 再检索（自动重载，0.9s 检索在重载后应变为 ~15s 一次）→ 关闭。数据写入手头汇报。
- [ ] 实测 footprint 前后对比 + 重载检索可用
