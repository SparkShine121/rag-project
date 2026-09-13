"""MultiSourceConnector 与共享 diff 归并逻辑测试。"""


from ragdb.config import SourceConfig
from ragdb.ingest.changeset import build_change_set
from ragdb.ingest.multi import MultiSourceConnector
from ragdb.ingest.schema import ChangeSet, RawDocument


def _doc(sid: str, content: str = "内容") -> RawDocument:
    return RawDocument(source_type="fake", source_id=sid, title=sid, content=content)


def _cfg(name: str) -> SourceConfig:
    return (SourceConfig(name=name, type="obsidian", path=f"/tmp/{name}")
            if name != "b" else
            SourceConfig(name=name, type="github", repo="o/r"))


class FakeSub:
    def __init__(self, all_docs=None, changes=None):
        self.all_docs = all_docs or []
        self.changes = changes or ChangeSet()
        self.known_received = None

    def fetch_all(self):
        return list(self.all_docs)

    def fetch_changes(self, known):
        self.known_received = dict(known)
        return self.changes


# ---------- build_change_set ----------

def test_build_change_set_classifies_all_four():
    known = {"keep.md": (1, 2, "h1"), "mod.md": (1, 2, "h2"),
             "del.md": (1, 2, "h3"), "mvold.md": (1, 2, "h4")}
    current = {"keep.md": (1, 2, "h1"), "mod.md": (1, 3, "h2b"),
               "new.md": (1, 2, "h4"), "add.md": (1, 1, "h5")}
    docs = {p: _doc(p) for p in current}
    cs = build_change_set(known, current, lambda p: docs[p])
    assert [d.source_id for d in cs.added] == ["add.md"]
    assert [d.source_id for d in cs.modified] == ["mod.md"]
    assert cs.moved == [("mvold.md", docs["new.md"])]
    assert cs.deleted == ["del.md"]
    assert cs.unchanged == 1


def test_build_change_set_hash_same_stamp_differs_is_unchanged():
    known = {"a.md": (1, 2, "h1")}
    current = {"a.md": (99, 2, "h1")}  # mtime 变了内容没变
    cs = build_change_set(known, current, lambda p: _doc(p))
    assert cs.unchanged == 1 and not cs.modified


def test_build_change_set_move_plus_modify_is_add_and_delete():
    known = {"old.md": (1, 2, "h1")}
    current = {"new.md": (1, 2, "h1b")}  # hash 变了 → 不算移动
    cs = build_change_set(known, current, lambda p: _doc(p))
    assert [d.source_id for d in cs.added] == ["new.md"]
    assert cs.deleted == ["old.md"] and not cs.moved


# ---------- RawDocument.hash_override ----------

def test_hash_override_takes_precedence():
    doc = _doc("x.md")
    plain = doc.content_hash
    doc2 = RawDocument(source_type="github", source_id="x.md", title="x",
                      content="内容", metadata={}, hash_override="gitblobsha")
    assert len(plain) == 64  # sha256 hex
    assert doc2.content_hash == "gitblobsha"


# ---------- MultiSourceConnector ----------

def test_fetch_all_prefixes_source_ids():
    multi = MultiSourceConnector([(_cfg("a"), FakeSub(all_docs=[_doc("1.md"), _doc("2.md")]))])
    docs = multi.fetch_all()
    assert [d.source_id for d in docs] == ["a/1.md", "a/2.md"]


def test_fetch_all_merges_multiple_sources():
    multi = MultiSourceConnector([
        (_cfg("a"), FakeSub(all_docs=[_doc("1.md")])),
        (_cfg("b"), FakeSub(all_docs=[_doc("1.md"), _doc("2.md")])),
    ])
    docs = multi.fetch_all()
    assert [d.source_id for d in docs] == ["a/1.md", "b/1.md", "b/2.md"]


def test_fetch_changes_routes_by_prefix_and_merges():
    sub_a = FakeSub(changes=ChangeSet(added=[_doc("1.md")], deleted=["gone.md"]))
    sub_b = FakeSub(changes=ChangeSet(moved=[("old.md", _doc("new.md"))]))
    multi = MultiSourceConnector([(_cfg("a"), sub_a), (_cfg("b"), sub_b)])
    known = {"a/1.md": (1, 1, "h"), "a/gone.md": (1, 1, "h"),
             "b/old.md": (1, 1, "h"), "zombie/x.md": (1, 1, "h")}
    cs = multi.fetch_changes(known)
    assert set(sub_a.known_received) == {"1.md", "gone.md"}
    assert set(sub_b.known_received) == {"old.md"}
    assert cs.added[0].source_id == "a/1.md"
    assert sorted(cs.deleted) == ["a/gone.md", "zombie/x.md"]  # 无主前缀整体删除
    assert cs.moved[0][0] == "b/old.md" and cs.moved[0][1].source_id == "b/new.md"


def test_source_prefixes():
    multi = MultiSourceConnector([(_cfg("a"), FakeSub()), (_cfg("b"), FakeSub())])
    assert multi.source_prefixes == ["a/", "b/"]
