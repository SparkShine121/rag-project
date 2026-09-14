"""ModelHub TTL 空闲卸载测试（fake 模型注入，零下载；契约见计划 2026-09-14）。"""

from ragdb.config import Settings
from ragdb.models.hub import BGEM3Embedder, ModelHub
from tests.helpers import FakeEmbedder, FakeReranker


class ReleasableFakeEmbedder(FakeEmbedder):
    def __init__(self, dim: int = 8):
        super().__init__(dim=dim)
        self.releases = 0

    def embed(self, texts):
        cb = getattr(self, "_on_use", None)
        cb and cb()
        return super().embed(texts)

    def release(self):
        self.releases += 1


class ReleasableFakeReranker(FakeReranker):
    def __init__(self):
        self.releases = 0

    def rerank(self, query, docs):
        cb = getattr(self, "_on_use", None)
        cb and cb()
        return super().rerank(query, docs)

    def release(self):
        self.releases += 1


def _hub(ttl: int, clock, **kw):
    s = Settings.load(path=None)
    return ModelHub(
        s,
        embedder_factory=lambda st: ReleasableFakeEmbedder(),
        reranker_factory=lambda st: ReleasableFakeReranker(),
        ttl_secs=ttl,
        clock=clock,
        **kw,
    )


def test_unload_idle_secs_default():
    assert Settings.load(path=None).unload_idle_secs == 1800


def test_embed_and_rerank_refresh_last_used():
    t = [100.0]
    hub = _hub(1800, clock=lambda: t[0])
    hub.embedder.embed(["x"])
    assert hub._last_used == 100.0
    t[0] = 150.0
    hub.embedder.embed_query("y")
    assert hub._last_used == 150.0
    hub.reranker.rerank("q", ["d"])
    assert hub._last_used == 150.0


def test_maybe_unload_noop_when_ttl_zero():
    t = [100.0]
    hub = _hub(0, clock=lambda: t[0])
    hub.embedder.embed(["x"])
    t[0] = 10**9
    assert hub.maybe_unload() is False
    assert hub.embedder.releases == 0


def test_maybe_unload_noop_within_ttl():
    t = [100.0]
    hub = _hub(1800, clock=lambda: t[0])
    hub.embedder.embed(["x"])
    t[0] = 100.0 + 1799
    assert hub.maybe_unload() is False
    assert hub.embedder.releases == 0


def test_maybe_unload_releases_after_ttl():
    t = [100.0]
    hub = _hub(1800, clock=lambda: t[0])
    emb = hub.embedder
    rr = hub.reranker
    emb.embed(["x"])
    t[0] = 100.0 + 1801
    assert hub.maybe_unload() is True
    assert emb.releases == 1 and rr.releases == 1
    assert hub._last_used is None  # 卸载后计时清零
    # 卸载后再次使用：懒重载路径（wrapper 仍在，权重重建）
    emb.embed(["y"])
    assert hub._last_used == t[0]
    # 卸载后 TTL 内未使用 → 不重复释放
    t[0] += 10
    assert hub.maybe_unload() is False
    assert emb.releases == 1


def test_maybe_unload_before_first_use_is_noop():
    t = [100.0]
    hub = _hub(1800, clock=lambda: t[0])
    t[0] = 10**6
    assert hub.maybe_unload() is False  # 从未加载过 → 无可释放


def test_hub_release_is_idempotent_on_real_wrappers():
    """BGEM3 wrapper 的 release 必须幂等且能复位 _model（不触发真实下载）。"""
    emb = BGEM3Embedder()
    emb.release()
    assert emb._model is None
    sentinel = object()
    emb._model = sentinel
    emb.release()
    assert emb._model is None
    emb.release()  # 幂等
    assert emb._model is None


def test_rerank_via_hub_refreshes_and_unloads():
    t = [0.0]
    hub = _hub(10, clock=lambda: t[0])
    rr = hub.reranker
    rr.rerank("q", ["d"])
    t[0] = 100.0
    assert hub.maybe_unload() is True
    assert rr.releases == 1
