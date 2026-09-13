"""来源装配工厂测试：配置 → 连接器实例的分发与鉴权。"""

import pytest

from ragdb.config import Settings, SourceConfig
from ragdb.ingest.connector import ObsidianConnector
from ragdb.ingest.factory import build_connectors
from ragdb.ingest.github import GitHubConnector
from ragdb.ingest.multi import MultiSourceConnector


def _settings(*sources: SourceConfig) -> Settings:
    return Settings(sources=list(sources))


def test_obsidian_source_builds_obsidian_connector(tmp_path):
    cfg = SourceConfig(name="obsidian", type="obsidian", path=str(tmp_path))
    items = build_connectors(_settings(cfg))
    assert len(items) == 1
    assert items[0][0].name == "obsidian"
    assert isinstance(items[0][1], ObsidianConnector)


def test_github_source_builds_github_connector_anonymous():
    cfg = SourceConfig(name="docs", type="github", repo="o/r")
    items = build_connectors(_settings(cfg))
    assert isinstance(items[0][1], GitHubConnector)


def test_github_token_from_env(monkeypatch):
    cfg = SourceConfig(name="docs", type="github", repo="o/r",
                       token_env="MY_TOKEN")
    monkeypatch.setenv("MY_TOKEN", "tok-xyz")
    items = build_connectors(_settings(cfg))
    assert items[0][1]._token == "tok-xyz"


def test_github_token_env_missing_rejects():
    cfg = SourceConfig(name="docs", type="github", repo="o/r",
                       token_env="MISSING_TOKEN_XYZ")
    with pytest.raises(ValueError, match="MISSING_TOKEN_XYZ"):
        build_connectors(_settings(cfg))


def test_multi_source_wrapped_in_multi_connector(tmp_path):
    cfgs = [SourceConfig(name="obsidian", type="obsidian", path=str(tmp_path)),
            SourceConfig(name="docs", type="github", repo="o/r")]
    items = build_connectors(_settings(*cfgs))
    assert isinstance(items, list) and len(items) == 2


def test_core_connector_is_multi_source(tmp_path):
    from ragdb.core import Core

    settings = Settings.load(path=None).model_copy(
        update={"data_dir": tmp_path / "d", "vault_path": tmp_path}
    )
    core = Core.from_settings(settings)
    assert isinstance(core.connector, MultiSourceConnector)
    assert core.connector.source_prefixes == ["obsidian/"]
