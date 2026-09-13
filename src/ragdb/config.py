"""配置加载：ragdb.toml + 环境变量覆盖（RAGDB_ 前缀）。"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class SourceConfig(BaseModel):
    """知识源配置：name 即 source_id 前缀（如 myrepo/docs/README.md）。"""

    name: str
    type: Literal["obsidian", "github"] = "obsidian"
    path: str | None = None        # obsidian 源
    repo: str | None = None        # github 源："owner/repo"
    ref: str = "main"
    token_env: str | None = None   # 私有仓库 token 的环境变量名；None = 匿名（公开仓库）

    @model_validator(mode="after")
    def _validate_kind(self) -> SourceConfig:
        if self.type == "github" and not self.repo:
            raise ValueError("github 缺 repo")
        if self.type == "obsidian" and not self.path:
            raise ValueError("obsidian 缺 path")
        return self


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
    rerank_top_k: int = 5  # 交叉编码只精排稠密分前 N 名（M4 实测约 100ms/对；5→0.7-1.2s，10→2.4s）
    sources: list[SourceConfig] = Field(default_factory=list)
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
        if path is None and not os.environ.get("RAGDB_NO_CWD_CONFIG"):
            # 默认发现：当前工作目录的 ragdb.toml（终审 I8）；
            # 测试环境通过 RAGDB_NO_CWD_CONFIG 隔离（tests/conftest.py）
            cwd_cfg = Path("ragdb.toml")
            path = cwd_cfg if cwd_cfg.exists() else None
        data: dict = {}
        if path is not None:
            data = tomllib.loads(Path(path).read_text(encoding="utf-8"))
            if "chunk" in data and isinstance(data["chunk"], dict):
                data["chunk"] = ChunkConfig(**data["chunk"])
            if "sources" in data:
                data["sources"] = [SourceConfig(**item) for item in data["sources"]]
        # 环境变量优先级高于 toml：仅识别 RAGDB_ 前缀（裸名如 PORT/DEVICE
        # 与 ragdb 无关，不得劫持 toml 值——终审 I2）
        for key in list(data):
            if f"RAGDB_{key.upper()}" in os.environ:
                data.pop(key)
        settings = cls(**data)
        settings.effective_sources()  # 触发来源校验（重名等），配置错误不启动
        return settings

    def effective_sources(self) -> list[SourceConfig]:
        """显式配置的来源；未配置时回退到 vault_path 单一 obsidian 源（v1 兼容）。"""
        if self.sources:
            names = [s.name for s in self.sources]
            if len(names) != len(set(names)):
                raise ValueError("sources 重名")
            return list(self.sources)
        return [SourceConfig(name="obsidian", type="obsidian",
                             path=str(self.vault_path))]
