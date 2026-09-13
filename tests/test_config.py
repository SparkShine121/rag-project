from pathlib import Path

import pytest
from pydantic import ValidationError

from ragdb.config import Settings


def test_defaults():
    s = Settings.load(path=None)
    assert s.port == 8770 and s.interval_secs == 30
    assert s.recall_k == 20 and s.top_k == 5 and s.token_budget == 3000
    assert s.chunk.min_chars == 100 and s.chunk.max_tokens == 500
    assert s.chunk.short_note_tokens == 600
    assert s.embed_model == "BAAI/bge-m3"
    assert s.rerank_model == "BAAI/bge-reranker-v2-m3"
    assert s.device == "mps" and s.dtype == "float16" and s.embed_batch == 32


def test_toml_override(tmp_path: Path):
    cfg = tmp_path / "ragdb.toml"
    cfg.write_text("port = 9000\ntop_k = 3\n", encoding="utf-8")
    s = Settings.load(path=cfg)
    assert s.port == 9000 and s.top_k == 3
    assert s.interval_secs == 30  # 未覆盖项保持默认


def test_dtype_rejects_invalid(tmp_path: Path):
    cfg = tmp_path / "ragdb.toml"
    cfg.write_text('dtype = "int8"\n', encoding="utf-8")
    with pytest.raises(ValidationError):
        Settings.load(path=cfg)


def test_env_overrides_toml(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    cfg = tmp_path / "ragdb.toml"
    cfg.write_text("port = 9000\n", encoding="utf-8")
    monkeypatch.setenv("RAGDB_PORT", "7000")
    assert Settings.load(path=cfg).port == 7000


def test_rerank_top_k_default():
    """冒烟实测：5 → 0.7-1.2s 达标且质量零损失（10 → 2.4s）。"""
    assert Settings.load(path=None).rerank_top_k == 5


# ---------- v1.1 多源配置 ----------

def test_effective_sources_falls_back_to_vault_path(tmp_path: Path):
    from ragdb.config import SourceConfig

    s = Settings.load(path=None).model_copy(update={"vault_path": tmp_path})
    eff = s.effective_sources()
    assert eff == [SourceConfig(name="obsidian", type="obsidian",
                                path=str(tmp_path))]


def test_sources_toml_parsing(tmp_path: Path):
    cfg = tmp_path / "ragdb.toml"
    cfg.write_text("""
[[sources]]
name = "obsidian"
type = "obsidian"
path = "~/Documents/Obsidian Vault"

[[sources]]
name = "docs"
type = "github"
repo = "owner/repo"
ref = "main"
token_env = "GITHUB_TOKEN"
""", encoding="utf-8")
    s = Settings.load(path=cfg)
    assert [x.name for x in s.sources] == ["obsidian", "docs"]
    assert s.sources[1].repo == "owner/repo"
    assert s.sources[1].token_env == "GITHUB_TOKEN"
    assert s.effective_sources() == s.sources  # 已显式配置时不回退


@pytest.mark.parametrize("toml,reason", [
    ((
        '[[sources]]\nname = "a"\ntype = "obsidian"\npath = "/tmp/x"\n'
        '[[sources]]\nname = "a"\ntype = "obsidian"\npath = "/tmp/y"\n'
     ), "重名"),
    ('[[sources]]\nname = "g"\ntype = "github"\n', "github 缺 repo"),
    ('[[sources]]\nname = "o"\ntype = "obsidian"\n', "obsidian 缺 path"),
])
def test_sources_validation_errors(tmp_path: Path, toml: str, reason: str):
    cfg = tmp_path / "ragdb.toml"
    cfg.write_text(toml, encoding="utf-8")
    with pytest.raises(Exception, match=reason):
        Settings.load(path=cfg)
