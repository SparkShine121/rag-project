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
    assert Settings.load(path=None).rerank_top_k == 10
