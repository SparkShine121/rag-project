"""MCP 进程空闲卸载巡检器测试。"""

import time

from ragdb.config import Settings
from ragdb.mcp_server import start_idle_unloader
from ragdb.models.hub import ModelHub
from tests.test_model_hub_ttl import ReleasableFakeEmbedder, ReleasableFakeReranker


class _Core:
    def __init__(self, hub):
        self.hub = hub


def _hub(ttl: int, clock):
    s = Settings.load(path=None)
    return ModelHub(
        s,
        embedder_factory=lambda st: ReleasableFakeEmbedder(),
        reranker_factory=lambda st: ReleasableFakeReranker(),
        ttl_secs=ttl,
        clock=clock,
    )


def test_watcher_calls_maybe_unload_periodically():
    t = [0.0]
    hub = _hub(1800, clock=lambda: t[0])
    core = _Core(hub)
    thread, stop = start_idle_unloader(core, interval_secs=1)
    try:
        time.sleep(0.35)  # interval=1s → 0 次触发属正常，只验证线程活着在等
        assert thread.is_alive()
    finally:
        stop.set()
        thread.join(timeout=2)
    assert not thread.is_alive()


def test_watcher_triggers_unload_after_ttl():
    t = [0.0]
    hub = _hub(2, clock=lambda: t[0])  # TTL 2s（真实墙钟等待 2.5s）
    core = _Core(hub)
    emb = hub.embedder  # 快照引用：后续轮询不得经属性刷新 TTL（属性访问=使用）
    emb.embed(["x"])  # _last_used = 0
    t[0] = 10.0  # clock 直接跳到 10s → 空闲 10s > 2s
    thread, stop = start_idle_unloader(core, interval_secs=1)
    try:
        deadline = time.time() + 3
        while emb.releases == 0 and time.time() < deadline:
            time.sleep(0.05)
        assert emb.releases == 1  # 巡检触发卸载
    finally:
        stop.set()
        thread.join(timeout=2)


def test_watcher_survives_hub_exception():
    class BoomHub:
        _ttl_secs = 1

        def maybe_unload(self):
            raise RuntimeError("boom")

    core = _Core(BoomHub())
    thread, stop = start_idle_unloader(core, interval_secs=1)
    try:
        time.sleep(0.35)
        assert thread.is_alive()  # 异常不杀线程
    finally:
        stop.set()
        thread.join(timeout=2)


def test_watcher_respects_stop_event_promptly():
    hub = _hub(0, clock=lambda: 0.0)
    core = _Core(hub)
    thread, stop = start_idle_unloader(core, interval_secs=30)
    stop.set()
    thread.join(timeout=2)
    assert not thread.is_alive()  # 长间隔下 stop 也能立即退出
