"""Core 装配点测试。"""

from pathlib import Path

from ragdb.config import Settings
from ragdb.core import Core
from tests.helpers import FakeEmbedder


def test_store_dim_derived_from_embedder(tmp_path: Path):
    """终审决策：dim 不得是魔法数字，由 embedder 声明推导（防换模型静默建错表）。"""
    settings = Settings.load(path=None).model_copy(
        update={"data_dir": tmp_path / "d", "vault_path": tmp_path}
    )
    core = Core.from_settings(settings)
    core.__dict__["embedder"] = FakeEmbedder(dim=8)
    assert core.store.dim == 8
