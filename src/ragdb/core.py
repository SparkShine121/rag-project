"""Core：全组件装配点（惰性构建、实例级缓存）。api/mcp/cli 的唯一入口。"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import cached_property

from ragdb.config import Settings


@dataclass
class Core:
    settings: Settings
    _connectors: list = field(default=None, repr=False)
    _extra: dict = field(default_factory=dict, repr=False)

    @classmethod
    def from_settings(cls, settings: Settings) -> Core:
        # 装配即校验：来源路径、GitHub 凭证等问题在此暴露，
        # serve/CLI/MCP 不得带病启动（终审 I3）；vault 校验移入工厂（终审 I5，
        # github-only 配置合法）。构建结果复用，避免重复建 httpx.Client（重审 N2）
        from ragdb.ingest.factory import build_connectors

        return cls(settings=settings, _connectors=build_connectors(settings))

    @cached_property
    def store(self):
        from ragdb.store.vector_store import VectorStore

        # dim 由嵌入模型声明推导，杜绝换模型后魔法数字静默建错表
        return VectorStore(self.settings.data_dir / "lancedb",
                           dim=self.embedder.dim)

    @cached_property
    def state(self):
        from ragdb.store.state import SyncState

        return SyncState(self.settings.data_dir / "state.db")

    @cached_property
    def connector(self):
        from ragdb.ingest.factory import build_connectors
        from ragdb.ingest.multi import MultiSourceConnector

        items = (self._connectors if self._connectors is not None
                 else build_connectors(self.settings))
        return MultiSourceConnector(items)

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

        return ModelHub(self.settings, ttl_secs=self.settings.unload_idle_secs)

    @cached_property
    def embedder(self):
        return self.hub.embedder

    @cached_property
    def reranker(self):
        return self.hub.reranker

    @cached_property
    def ingest_pipeline(self):
        from ragdb.ingest.code import CodeChunker
        from ragdb.ingest.ocr import available as ocr_available
        from ragdb.ingest.ocr import recognize_png
        from ragdb.ingest.pdf import PdfParser
        from ragdb.ingest.pipeline import IngestPipeline

        return IngestPipeline(
            chunker=self.chunker,
            code_chunker=CodeChunker(token_counter=self.chunker.count,
                                     max_tokens=self.settings.chunk.max_tokens),
            pdf_parser=PdfParser(
                ocr_fn=recognize_png if ocr_available() else None,
                token_counter=self.chunker.count,
            ),
        )

    @cached_property
    def engine(self):
        from ragdb.sync.engine import SyncEngine

        return SyncEngine(
            self.connector, self.embedder, self.store, self.state, self.chunker,
            pipeline=self.ingest_pipeline,
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
