from pathlib import Path

from ragdb.store.state import SyncState


def test_roundtrip_and_overwrite(tmp_path: Path):
    st = SyncState(tmp_path / "state.db")
    st.upsert("a.md", 111.0, 10, "hash-a", 3)
    st.upsert("b.md", 222.0, 20, "hash-b", 1)
    all_stamps = st.get_all()
    assert all_stamps["a.md"] == (111.0, 10, "hash-a")
    assert all_stamps["b.md"] == (222.0, 20, "hash-b")

    st.upsert("a.md", 333.0, 12, "hash-a2", 4)  # 覆盖更新
    assert st.get_all()["a.md"] == (333.0, 12, "hash-a2")
    assert len(st.get_all()) == 2


def test_delete(tmp_path: Path):
    st = SyncState(tmp_path / "state.db")
    st.upsert("a.md", 1.0, 1, "h", 1)
    st.delete("a.md")
    assert "a.md" not in st.get_all()
    st.delete("a.md")  # 幂等
    assert st.get_all() == {}


def test_meta(tmp_path: Path):
    st = SyncState(tmp_path / "state.db")
    assert st.get_meta("last_sync") is None
    assert st.get_meta("last_sync", "never") == "never"
    st.set_meta("last_sync", "2026-09-08T12:00:00")
    assert st.get_meta("last_sync") == "2026-09-08T12:00:00"
    st.set_meta("last_sync", "2026-09-08T13:00:00")  # 覆盖
    assert st.get_meta("last_sync") == "2026-09-08T13:00:00"


def test_persistence_across_instances(tmp_path: Path):
    SyncState(tmp_path / "state.db").upsert("a.md", 1.0, 1, "h", 2)
    assert SyncState(tmp_path / "state.db").get_all()["a.md"] == (1.0, 1, "h")
