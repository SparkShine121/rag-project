import numpy as np
import pytest

from ragdb.config import Settings
from ragdb.models.hub import BGEM3Embedder, BGEM3Reranker, Embedder, ModelHub, Reranker
from tests.helpers import FakeEmbedder, FakeReranker


def test_fake_embedder_deterministic_and_normalized():
    emb = FakeEmbedder(dim=8)
    v1 = emb.embed_query("你好世界")
    v2 = emb.embed_query("你好世界")
    v3 = emb.embed_query("完全不同")
    assert v1.shape == (8,)
    assert np.allclose(v1, v2)
    assert not np.allclose(v1, v3)
    assert np.linalg.norm(v1) == pytest.approx(1.0)


def test_fake_embedder_batch_shape():
    emb = FakeEmbedder(dim=8)
    out = emb.embed(["a", "b", "c"])
    assert out.shape == (3, 8)


def test_fake_reranker_prefers_overlap():
    rr = FakeReranker()
    scores = rr.rerank("机器学习", ["机器学习入门", "今天天气不错", "机器学习与深度学习"])
    assert scores[0] > scores[1]
    assert scores[2] > scores[1]  # 两个相关文档都应高于无关文档


def test_protocols_satisfied():
    assert isinstance(FakeEmbedder(dim=8), Embedder)
    assert isinstance(FakeReranker(), Reranker)


def test_real_classes_exist_and_have_dim():
    assert BGEM3Embedder.dim == 1024
    assert BGEM3Reranker is not None  # 构造不触发下载（懒加载）


def test_hub_lazy_and_cached():
    calls = []

    def fac(settings):
        calls.append(1)
        return FakeEmbedder(dim=8)

    hub = ModelHub(Settings.load(path=None), embedder_factory=fac)
    assert not calls  # 未访问不构建
    _ = hub.embedder
    _ = hub.embedder
    assert len(calls) == 1  # 缓存生效
