"""模型层：嵌入/重排协议、bge-m3 真实实现（懒加载）与 ModelHub。"""

from __future__ import annotations

import logging
import time
from typing import Protocol, runtime_checkable

import numpy as np

from ragdb.config import Settings

logger = logging.getLogger("ragdb.models")


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

    def release(self) -> None:
        """释放已加载权重（幂等）；下次访问 .model 自动从 HF 缓存重载。"""
        self._model = None
        try:
            import torch

            if torch.backends.mps.is_available():
                torch.mps.empty_cache()
        except Exception:  # noqa: BLE001, S110 —— 清理失败不致命且无可记录处
            pass

    def __init__(
        self, model_name: str = "BAAI/bge-m3", device: str = "mps",
        dtype: str = "float16", batch_size: int = 32,
    ):
        self._model_name = model_name
        self._devices = [device] if device else None
        self._dtype = dtype
        self._batch_size = batch_size
        self._model = None

    @property
    def model(self):
        if self._model is None:
            from FlagEmbedding import BGEM3FlagModel

            # FlagEmbedding 的设备自动探测只认 CUDA：必须显式传 devices，
            # 否则 MPS 落回 CPU，且 CPU+fp16 是最慢组合（真实冒烟实测）
            self._model = BGEM3FlagModel(
                self._model_name, use_fp16=(self._dtype == "float16"),
                devices=self._devices,
            )
        return self._model

    def embed(self, texts: list[str]) -> np.ndarray:
        cb = getattr(self, "_on_use", None)
        cb and cb()  # TTL 计时：hub 注入的使用回调
        if not texts:
            return np.empty((0, self.dim), dtype="float32")
        model = self.model  # 局部引用：卸载不影响 in-flight 调用
        out = model.encode(
            texts, batch_size=self._batch_size, max_length=1024
        )["dense_vecs"]
        return _l2_normalize(np.asarray(out, dtype="float32"))

    def embed_query(self, query: str) -> np.ndarray:
        return self.embed([query])[0]


class BGEM3Reranker:
    def release(self) -> None:
        self._model = None
        try:
            import torch

            if torch.backends.mps.is_available():
                torch.mps.empty_cache()
        except Exception:  # noqa: BLE001, S110 —— 清理失败不致命且无可记录处
            pass

    def __init__(
        self, model_name: str = "BAAI/bge-reranker-v2-m3", device: str = "mps",
        dtype: str = "float16",
    ):
        self._model_name = model_name
        self._devices = [device] if device else None
        self._dtype = dtype
        self._model = None

    @property
    def model(self):
        if self._model is None:
            from FlagEmbedding import FlagReranker

            self._model = FlagReranker(
                self._model_name, use_fp16=(self._dtype == "float16"),
                devices=self._devices,
            )
        return self._model

    def rerank(self, query: str, docs: list[str]) -> list[float]:
        cb = getattr(self, "_on_use", None)
        cb and cb()  # TTL 计时：hub 注入的使用回调
        if not docs:
            return []
        model = self.model  # 局部引用：卸载不影响 in-flight 调用
        scores = model.compute_score(
            [[query, d] for d in docs], normalize=True
        )
        if isinstance(scores, (int, float)):
            return [float(scores)]
        return [float(s) for s in scores]


class ModelHub:
    """懒加载单例：embedder 在同步/检索首用时构建，reranker 首次 search 才构建。

    TTL 空闲卸载（v1.3）：wrapper 对象常驻（Retriever/Engine 持有引用安全），
    maybe_unload 在空闲超时后仅释放权重（release()），下次使用自动重载。
    """

    def __init__(
        self, settings: Settings,
        embedder_factory=None, reranker_factory=None,
        ttl_secs: int = 0, clock=time.monotonic,
    ):
        self._settings = settings
        self._embedder_factory = embedder_factory
        self._reranker_factory = reranker_factory
        self._embedder: Embedder | None = None
        self._reranker: Reranker | None = None
        self._ttl_secs = ttl_secs
        self._clock = clock
        self._last_used: float | None = None

    def _touch(self) -> None:
        self._last_used = self._clock()

    def release(self) -> None:
        """立即释放两个模型的权重（幂等）。"""
        for model in (self._embedder, self._reranker):
            release = getattr(model, "release", None)
            if release is not None:
                logger.warning("释放模型权重: %s", type(model).__name__)
                release()
        self._last_used = None

    def idle_secs(self) -> float | None:
        """距上次使用的秒数；未使用过返回 None。"""
        return None if self._last_used is None else self._clock() - self._last_used

    def maybe_unload(self, now: float | None = None) -> bool:
        """空闲超过 TTL 且已加载过 → 释放权重并返回 True；否则 False。"""
        if self._ttl_secs <= 0 or self._last_used is None:
            return False
        now = self._clock() if now is None else now
        idle = now - self._last_used
        if idle <= self._ttl_secs:
            return False
        logger.warning("模型空闲 %.0fs 超过 TTL %ds，执行卸载", idle, self._ttl_secs)
        self.release()
        return True

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
            self._embedder._on_use = self._touch
        self._touch()
        return self._embedder

    @property
    def reranker(self) -> Reranker:
        if self._reranker is None:
            if self._reranker_factory is not None:
                self._reranker = self._reranker_factory(self._settings)
            else:
                s = self._settings
                self._reranker = BGEM3Reranker(s.rerank_model, s.device, s.dtype)
            self._reranker._on_use = self._touch
        self._touch()
        return self._reranker
