"""真实模型慢速测试：需 RAGDB_SLOW=1 且网络可达 hf-mirror。快速测试套件自动跳过。"""

import os

import pytest

pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(
        os.environ.get("RAGDB_SLOW") != "1", reason="需要 RAGDB_SLOW=1"
    ),
]


def test_real_embedder_dim_and_semantics():
    from ragdb.models.hub import BGEM3Embedder

    emb = BGEM3Embedder()
    out = emb.embed(["机器学习是人工智能的一个分支", "深度学习属于机器学习", "今天中午吃了红烧肉"])
    assert out.shape == (3, 1024)
    sims = out @ out.T
    assert sims[0, 1] > sims[0, 2]  # 相关句相似度 > 无关句


def test_real_reranker_prefers_relevant():
    from ragdb.models.hub import BGEM3Reranker

    rr = BGEM3Reranker()
    scores = rr.rerank(
        "什么是检索增强生成",
        ["RAG 通过检索外部知识库增强大模型回答", "苹果是一种水果", "检索增强生成的原理与实现"],
    )
    assert scores[0] > scores[1] and scores[2] > scores[1]
