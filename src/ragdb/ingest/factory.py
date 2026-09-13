"""来源装配：SourceConfig 列表 → 连接器实例。私有仓库 token 缺失时不启动。"""

from __future__ import annotations

import os
from pathlib import Path

from ragdb.config import Settings, SourceConfig
from ragdb.ingest.connector import ObsidianConnector, SourceConnector
from ragdb.ingest.folder import FolderConnector
from ragdb.ingest.github import GitHubConnector


def build_connectors(settings: Settings) -> list[tuple[SourceConfig, SourceConnector]]:
    items: list[tuple[SourceConfig, SourceConnector]] = []
    for cfg in settings.effective_sources():
        if cfg.type == "obsidian":
            path = Path(cfg.path).expanduser()
            if not path.exists():  # 装配即校验：来源路径问题不启动（终审 I3/I5）
                raise FileNotFoundError(
                    f"知识源路径不存在: {path}（来源 '{cfg.name}'）"
                )
            items.append((cfg, ObsidianConnector(path)))
        elif cfg.type == "folder":
            path = Path(cfg.path).expanduser()
            if not path.exists():
                raise FileNotFoundError(
                    f"知识源路径不存在: {path}（来源 '{cfg.name}'）"
                )
            items.append((cfg, FolderConnector(cfg, settings.effective_ingest(cfg))))
        elif cfg.type == "github":
            token = os.environ.get(cfg.token_env) if cfg.token_env else None
            if cfg.token_env and token is None:
                raise ValueError(
                    f"GitHub 源 '{cfg.name}' 需要 token：环境变量 {cfg.token_env} 未设置"
                    f"（私有仓库必须提供；公开仓库可去掉 token_env 配置）"
                )
            items.append((cfg, GitHubConnector(cfg, token=token,
                                 ingest_cfg=settings.effective_ingest(cfg))))
        else:  # pragma: no cover —— Literal 类型约束兜底
            raise ValueError(f"未知来源类型: {cfg.type}")
    return items
