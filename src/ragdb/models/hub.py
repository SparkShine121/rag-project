"""模型层：嵌入/重排协议、bge-m3 真实实现（懒加载）与 ModelHub。"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

import numpy as np

from ragdb.config import Settings


@runtime_checkable
class Embedder(Protocol):
    dim: int

    def embed(self, texts: list[str]) -> np.ndarray: ...

    def embed_query(self, query: str) -> np.ndarray: ...


@runtime_checkable
class Reranker(Protocol):
    def rerank(self, query: str, docs: list[str]) -> list[float]: ...


def _l2_normalize(mat: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(mat, axis=1, keepdims=True)
    return mat / np.clip(norms, 1e-12, None)


class BGEM3Embedder:
    dim = 1024

    def __init__(
        self, model_name: str = "BAAI/bge-m3", device: str = "mps",
        dtype: str = "float16", batch_size: int = 32,
    ):
        self._model_name = model_name
        self._device = device
        self._dtype = dtype
        self._batch_size = batch_size
        self._model = None

    @property
    def model(self):
        if self._model is None:
            from FlagEmbedding import BGEM3FlagModel

            self._model = BGEM3FlagModel(
                self._model_name, use_fp16=(self._dtype == "float16"),
                device=self._device,
            )
        return self._model

    def embed(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.empty((0, self.dim), dtype="float32")
        out = self.model.encode(
            texts, batch_size=self._batch_size, max_length=1024
        )["dense_vecs"]
        return _l2_normalize(np.asarray(out, dtype="float32"))

    def embed_query(self, query: str) -> np.ndarray:
        return self.embed([query])[0]


class BGEM3Reranker:
    def __init__(
        self, model_name: str = "BAAI/bge-reranker-v2-m3", device: str = "mps",
        dtype: str = "float16",
    ):
        self._model_name = model_name
        self._device = device
        self._dtype = dtype
        self._model = None

    @property
    def model(self):
        if self._model is None:
            from FlagEmbedding import FlagReranker

            self._model = FlagReranker(
                self._model_name, use_fp16=(self._dtype == "float16"),
                device=self._device,
            )
        return self._model

    def rerank(self, query: str, docs: list[str]) -> list[float]:
        if not docs:
            return []
        scores = self.model.compute_score(
            [[query, d] for d in docs], normalize=True
        )
        if isinstance(scores, (int, float)):
            return [float(scores)]
        return [float(s) for s in scores]


class ModelHub:
    """懒加载单例：embedder 在同步/检索首用时构建，reranker 首次 search 才构建。"""

    def __init__(
        self, settings: Settings,
        embedder_factory=None, reranker_factory=None,
    ):
        self._settings = settings
        self._embedder_factory = embedder_factory
        self._reranker_factory = reranker_factory
        self._embedder: Embedder | None = None
        self._reranker: Reranker | None = None

    @property
    def embedder(self) -> Embedder:
        if self._embedder is None:
            if self._embedder_factory is not None:
                self._embedder = self._embedder_factory(self._settings)
            else:
                s = self._settings
                self._embedder = BGEM3Embedder(
                    s.embed_model, s.device, s.dtype, s.embed_batch
                )
        return self._embedder

    @property
    def reranker(self) -> Reranker:
        if self._reranker is None:
            if self._reranker_factory is not None:
                self._reranker = self._reranker_factory(self._settings)
            else:
                s = self._settings
                self._reranker = BGEM3Reranker(s.rerank_model, s.device, s.dtype)
        return self._reranker
