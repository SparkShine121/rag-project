"""v1.3.2 serve 空闲退出（supervised exit）判定与在飞计数测试。"""

from fastapi.testclient import TestClient

from ragdb.api.app import create_app, idle_exit_due

# ── idle_exit_due 四条判定边界 ────────────────────────────


def test_no_exit_without_supervision():
    # 无监督（终端直跑）永不自杀，回落 v1.3 卸载行为
    assert idle_exit_due(idle=100.0, ttl=15, supervised=False, inflight=0) is False


def test_no_exit_while_search_inflight():
    # 在飞检索期间绝不退出（重连只保下次调用，不保进行中的调用）
    assert idle_exit_due(idle=100.0, ttl=15, supervised=True, inflight=1) is False


def test_no_exit_when_model_never_loaded():
    # 模型从未加载（idle=None）已是目标内存，退出只会造成重启 churn
    assert idle_exit_due(idle=None, ttl=15, supervised=True, inflight=0) is False


def test_exit_only_strictly_after_ttl():
    # 等号不退（严格大于）；超过才退
    assert idle_exit_due(idle=15.0, ttl=15, supervised=True, inflight=0) is False
    assert idle_exit_due(idle=15.1, ttl=15, supervised=True, inflight=0) is True


# ── search 端点在飞计数器 ────────────────────────────────


def test_search_endpoint_tracks_inflight_counter():
    seen = []

    class FakeRetriever:
        def search(self, *args, **kwargs):
            seen.append(app.state.search_inflight)  # 进入时计数应为 1
            return []

    class FakeCore:
        retriever = FakeRetriever()

    app = create_app(FakeCore())
    client = TestClient(app)
    resp = client.post("/api/v1/search", json={"query": "x"})
    assert resp.status_code == 200
    assert seen == [1]  # 检索执行期间计数为 1
    assert app.state.search_inflight == 0  # 结束后归零（try/finally）
