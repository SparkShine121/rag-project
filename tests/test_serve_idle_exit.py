"""v1.3.2 serve 空闲退出（supervised exit）判定与在飞计数测试。"""

from fastapi.testclient import TestClient

from ragdb.api.app import create_app, idle_exit_due
from ragdb.core import InflightTracker
from ragdb.mcp_server import _tool_search

# ── idle_exit_due 五条判定边界 ────────────────────────────


def test_no_exit_without_supervision():
    # 无监督（终端直跑）永不自杀，回落 v1.3 卸载行为
    assert idle_exit_due(idle=100.0, ttl=15, supervised=False, inflight=0) is False


def test_no_exit_while_search_inflight():
    # 在飞检索期间绝不退出（重连只保下次调用，不保进行中的调用）
    assert idle_exit_due(idle=100.0, ttl=15, supervised=True, inflight=1) is False


def test_no_exit_when_model_never_loaded():
    # 模型从未加载（idle=None）已是目标内存，退出只会造成重启 churn
    assert idle_exit_due(idle=None, ttl=15, supervised=True, inflight=0) is False


def test_no_exit_when_ttl_zero():
    # ttl<=0 = 常驻不卸载不退出（ragdb.toml 契约；镜像 hub.maybe_unload 的守卫）
    assert idle_exit_due(idle=30.0, ttl=0, supervised=True, inflight=0) is False
    assert idle_exit_due(idle=30.0, ttl=-1, supervised=True, inflight=0) is False


def test_exit_only_strictly_after_ttl():
    # 等号不退（严格大于）；超过才退
    assert idle_exit_due(idle=15.0, ttl=15, supervised=True, inflight=0) is False
    assert idle_exit_due(idle=15.1, ttl=15, supervised=True, inflight=0) is True


# ── InflightTracker（REST 与 MCP 共享的安全阀） ─────────────


def test_tracker_counts_during_and_resets_after():
    tracker = InflightTracker()
    with tracker.track():
        assert tracker.count == 1
        with tracker.track():
            assert tracker.count == 2  # 并发窗口可嵌套
    assert tracker.count == 0


def test_tracker_resets_on_exception():
    tracker = InflightTracker()
    try:
        with tracker.track():
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    assert tracker.count == 0  # 异常路径也必须归零


def test_tracker_thread_safe_counts():
    import threading

    tracker = InflightTracker()

    def worker():
        with tracker.track():
            pass

    threads = [threading.Thread(target=worker) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert tracker.count == 0  # 20 线程各进出一轮，无丢失


# ── REST / MCP 两通道共用同一计数器（终审 S2） ──────────────


class RecorderCore:
    """带真实 InflightTracker 的最小 Fake Core，检索时记录执行窗口内的计数。"""

    def __init__(self):
        self.search_inflight = InflightTracker()
        self.seen = []
        outer = self

        class _Recorder:
            def search(self, *args, **kwargs):
                outer.seen.append(outer.search_inflight.count)
                return []

        self.retriever = _Recorder()


def test_rest_endpoint_counts_inflight():
    core = RecorderCore()
    resp = TestClient(create_app(core)).post("/api/v1/search", json={"query": "x"})
    assert resp.status_code == 200
    assert core.seen == [1]  # REST 检索执行期间计数为 1
    assert core.search_inflight.count == 0  # 结束归零


def test_mcp_tool_search_counts_inflight():
    core = RecorderCore()
    assert _tool_search(core, "查询") == "未找到相关内容。"
    assert core.seen == [1]  # MCP 通道同口径
    assert core.search_inflight.count == 0  # 结束归零


def test_rest_and_mcp_share_tracker_instance():
    core = RecorderCore()
    with core.search_inflight.track():  # 模拟 REST 侧持有的窗口
        _tool_search(core, "查询")  # MCP 通道在同一 core 上检索
        assert core.seen == [2]  # 外层 1 + MCP 进入 → 2，证明同一实例
