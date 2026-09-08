"""Core：全组件装配点（惰性构建、实例级缓存）。api/mcp/cli 的唯一入口。"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import cached_property

from ragdb.config import Settings


@dataclass
class Core:
    settings: Settings
    _extra: dict = field(default_factory=dict, repr=False)

    @classmethod
    def from_settings(cls, settings: Settings) -> Core:
        if not settings.vault_path.exists():  # spec §7：配置校验不过不启动
            raise FileNotFoundError(
                f"知识库路径不存在: {settings.vault_path}（检查 ragdb.toml 的 vault_path）"
            )
        return cls(settings=settings)

    @cached_property
    def store(self):
        from ragdb.store.vector_store import VectorStore

        return VectorStore(self.settings.data_dir / "lancedb")

    @cached_property
    def state(self):
        from ragdb.store.state import SyncState

        return SyncState(self.settings.data_dir / "state.db")

    @cached_property
    def connector(self):
        from ragdb.ingest.connector import ObsidianConnector

        return ObsidianConnector(self.settings.vault_path)

    @cached_property
    def chunker(self):
        from ragdb.ingest.chunker import Chunker

        return Chunker(
            min_chars=self.settings.chunk.min_chars,
            max_tokens=self.settings.chunk.max_tokens,
        )

    @cached_property
    def hub(self):
        from ragdb.models.hub import ModelHub

        return ModelHub(self.settings)

    @cached_property
    def embedder(self):
        return self.hub.embedder

    @cached_property
    def reranker(self):
        return self.hub.reranker

    @cached_property
    def engine(self):
        from ragdb.sync.engine import SyncEngine

        return SyncEngine(
            self.connector, self.embedder, self.store, self.state, self.chunker
        )

    @cached_property
    def retriever(self):
        from ragdb.retrieve.retriever import Retriever

        return Retriever(
            self.embedder, self.reranker, self.store,
            self.chunker.count,
            recall_k=self.settings.recall_k, top_k=self.settings.top_k,
            rerank_top_k=self.settings.rerank_top_k,
            token_budget=self.settings.token_budget,
            short_note_tokens=self.settings.chunk.short_note_tokens,
        )
