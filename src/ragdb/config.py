"""配置加载：ragdb.toml + 环境变量覆盖（RAGDB_ 前缀）。"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ChunkConfig(BaseModel):
    min_chars: int = 100
    max_tokens: int = 500
    short_note_tokens: int = 600


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RAGDB_", extra="ignore")

    vault_path: Path = Path("~/Documents/Obsidian Vault")
    data_dir: Path = Path("~/Library/Application Support/ragdb")
    port: int = 8770
    interval_secs: int = 30
    recall_k: int = 20
    top_k: int = 5
    token_budget: int = 3000
    chunk: ChunkConfig = Field(default_factory=ChunkConfig)
    embed_model: str = "BAAI/bge-m3"
    rerank_model: str = "BAAI/bge-reranker-v2-m3"
    device: str = "mps"
    dtype: Literal["float16", "float32"] = "float16"
    embed_batch: int = 32

    @field_validator("vault_path", "data_dir", mode="after")
    @classmethod
    def _expand(cls, v: Path) -> Path:
        return v.expanduser()

    @classmethod
    def load(cls, path: Path | None = None) -> Settings:
        data: dict = {}
        if path is not None:
            data = tomllib.loads(path.read_text(encoding="utf-8"))
            if "chunk" in data and isinstance(data["chunk"], dict):
                data["chunk"] = ChunkConfig(**data["chunk"])
        # 环境变量优先级高于 toml：env 接管的字段不传 init kwargs
        #（BaseSettings 的 init 优先级最高，会让 toml 反压 env）
        for key in list(data):
            if key.upper() in os.environ or f"RAGDB_{key.upper()}" in os.environ:
                data.pop(key)
        return cls(**data)
