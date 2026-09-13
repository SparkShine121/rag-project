"""GitHubConnector 测试：Git Blobs API 版（v1.2，无 Contents 1MB 上限）。"""

import base64

import httpx
import pytest

from ragdb.config import IngestConfig, SourceConfig
from ragdb.ingest.github import GitHubConnector

TREE = {
    "tree": [
        {"path": "docs/a.md", "type": "blob", "sha": "shaA", "size": 10},
        {"path": "code/main.py", "type": "blob", "sha": "shaP", "size": 10},
        {"path": "README.md", "type": "blob", "sha": "shaR", "size": 5},
    ],
    "truncated": False,
}

CONTENT_A = "# 文档 A\n\n内容正文"


def _handler(routes: dict, calls: list):
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        for (method, suffix), (status, payload) in routes.items():
            if request.method == method and request.url.path.endswith(suffix):
                return httpx.Response(status, json=payload)
        return httpx.Response(404, json={"message": "not found"})

    return handler


def _client(routes: dict, calls: list) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(_handler(routes, calls)),
                        base_url="https://api.github.com")


def _cfg(**kw) -> SourceConfig:
    return SourceConfig(name="repo1", type="github", repo="o/r", **kw)


def _routes(tree=TREE) -> dict:
    """Git Blobs API 路由：内容按 sha 拉取（无 Contents API 1MB 上限）。"""
    return {
        ("GET", "/git/trees/main"): (200, tree),
        ("GET", "/git/blobs/shaA"): (200, {"content": base64.b64encode(CONTENT_A.encode()).decode(),
                                           "encoding": "base64", "size": 10}),
        ("GET", "/git/blobs/shaR"): (200, {"content": base64.b64encode("说明".encode()).decode(),
                                           "encoding": "base64", "size": 5}),
        ("GET", "/git/blobs/shaP"): (200, {"content": base64.b64encode(b"x=1\n").decode(),
                                           "encoding": "base64", "size": 4}),
    }


def test_fetch_all_only_md_and_decoded():
    calls: list = []
    conn = GitHubConnector(_cfg(), client=_client(_routes(), calls))
    docs = conn.fetch_all()
    assert sorted(d.source_id for d in docs) == ["README.md", "docs/a.md"]
    a = next(d for d in docs if d.source_id == "docs/a.md")
    assert a.content == CONTENT_A
    assert a.hash_override == "shaA" and a.content_hash == "shaA"
    assert a.metadata["html_url"] == "https://github.com/o/r/blob/main/docs/a.md"
    assert a.source_type == "github"


def test_fetch_all_without_token_has_no_auth_header():
    calls: list = []
    GitHubConnector(_cfg(), client=_client(_routes(), calls)).fetch_all()
    assert all("authorization" not in h.headers for h in calls)


def test_fetch_all_with_token_sends_bearer():
    calls: list = []
    GitHubConnector(_cfg(), token="tok123", client=_client(_routes(), calls)).fetch_all()
    assert all(h.headers.get("authorization") == "Bearer tok123" for h in calls)


def test_fetch_changes_skip_unchanged_download():
    calls: list = []
    tree = {"tree": [{"path": "README.md", "type": "blob", "sha": "shaR", "size": 5}],
            "truncated": False}  # docs/a.md 已从仓库消失
    conn = GitHubConnector(_cfg(), client=_client(_routes(tree), calls))
    known = {"README.md": (0.0, 5, "shaR"), "docs/a.md": (0.0, 10, "shaA")}
    cs = conn.fetch_changes(known)
    assert cs.unchanged == 1 and cs.deleted == ["docs/a.md"]
    assert sum(1 for c in calls if "/git/blobs/" in c.url.path) == 0  # 未变更零下载


def test_fetch_changes_modified_file_downloaded():
    tree = {"tree": [{"path": "README.md", "type": "blob", "sha": "shaR2", "size": 6}],
            "truncated": False}
    routes = {("GET", "/git/trees/main"): (200, tree),
              ("GET", "/git/blobs/shaR2"): (200, {"content": base64.b64encode("新版".encode()).decode(),
                                                  "encoding": "base64", "size": 6})}
    conn = GitHubConnector(_cfg(), client=_client(routes, []))
    cs = conn.fetch_changes({"README.md": (0.0, 5, "shaR")})
    assert [d.source_id for d in cs.modified] == ["README.md"]
    assert cs.modified[0].content_hash == "shaR2"


def test_fetch_changes_moved_detected_via_blob_sha():
    tree = {"tree": [{"path": "new/位置.md", "type": "blob", "sha": "shaA", "size": 10}],
            "truncated": False}
    conn = GitHubConnector(_cfg(), client=_client(_routes(tree), []))
    cs = conn.fetch_changes({"docs/a.md": (0.0, 10, "shaA")})
    assert cs.moved[0][0] == "docs/a.md"
    assert cs.moved[0][1].source_id == "new/位置.md"


def test_repo_not_found_or_private_hint():
    conn = GitHubConnector(_cfg(), client=_client({}, []))
    with pytest.raises(ValueError, match="私有|token|不存在"):
        conn.fetch_all()


def test_auth_failure_hint():
    routes = {("GET", "/git/trees/main"): (401, {"message": "Bad credentials"})}
    conn = GitHubConnector(_cfg(), client=_client(routes, []))
    with pytest.raises(ValueError, match="认证|token"):
        conn.fetch_all()


def test_truncated_tree_rejected():
    conn = GitHubConnector(_cfg(), client=_client(_routes(dict(TREE, truncated=True)), []))
    with pytest.raises(ValueError, match="截断"):
        conn.fetch_all()


def test_title_from_h1_not_frontmatter():
    tree = {"tree": [{"path": "t.md", "type": "blob", "sha": "shaT", "size": 5}],
            "truncated": False}
    routes = {("GET", "/git/trees/main"): (200, tree),
              ("GET", "/git/blobs/shaT"): (200, {
                  "content": base64.b64encode("---\n# 假标题\ntags: [x]\n---\n# 真标题\n正文".encode()).decode(),
                  "encoding": "base64", "size": 5})}
    conn = GitHubConnector(_cfg(), client=_client(routes, []))
    assert conn.fetch_all()[0].title == "真标题"


# ---------- v1.2 白名单扩展（Git Blobs API 无 1MB 上限）----------

def test_whitelist_exts_and_pdf_binary():
    tree = {"tree": [
        {"path": "a.md", "type": "blob", "sha": "shaM", "size": 5},
        {"path": "b.pdf", "type": "blob", "sha": "shaP", "size": 9},
        {"path": "c.py", "type": "blob", "sha": "shaC", "size": 5},
    ], "truncated": False}
    routes = {("GET", "/git/trees/main"): (200, tree),
              ("GET", "/git/blobs/shaM"): (200, {"content": base64.b64encode("文档".encode()).decode(),
                                                 "encoding": "base64", "size": 5}),
              ("GET", "/git/blobs/shaP"): (200, {"content": base64.b64encode(b"%PDF fake").decode(),
                                                 "encoding": "base64", "size": 9})}
    conn = GitHubConnector(_cfg(), client=_client(routes, []),
                           ingest_cfg=IngestConfig(include_exts=[".md", ".pdf"]))
    docs = conn.fetch_all()
    assert {d.source_id for d in docs} == {"a.md", "b.pdf"}  # c.py 被白名单排除
    pdf = next(d for d in docs if d.source_id == "b.pdf")
    assert pdf.binary == b"%PDF fake" and pdf.content == ""


def test_oversized_github_file_skipped_with_hint():
    tree = {"tree": [
        {"path": "big.pdf", "type": "blob", "sha": "shaB", "size": 60 * 1024 * 1024},
        {"path": "small.md", "type": "blob", "sha": "shaS", "size": 3},
    ], "truncated": False}
    routes = {("GET", "/git/trees/main"): (200, tree),
              ("GET", "/git/blobs/shaS"): (200, {"content": base64.b64encode(b"ok").decode(),
                                                 "encoding": "base64", "size": 3})}
    calls: list = []
    conn = GitHubConnector(_cfg(), client=_client(routes, calls),
                           ingest_cfg=IngestConfig(include_exts=[".md", ".pdf"],
                                                   max_file_mb=50))
    cs = conn.fetch_changes({})
    assert [d.source_id for d in cs.added] == ["small.md"]
    assert any("超过大小上限" in r for _, r in cs.failed)
    assert sum(1 for c in calls if "/git/blobs/shaB" in c.url.path) == 0  # 超限不下载


def test_max_files_cap_hint():
    """终审 I2：GitHub 源同样受 max_files_per_source 约束。"""
    tree = {"tree": [{"path": f"f{i}.md", "type": "blob", "sha": f"s{i}", "size": 3}
                     for i in range(5)], "truncated": False}
    routes = {("GET", "/git/trees/main"): (200, tree),
              **{("GET", f"/git/blobs/s{i}"): (200, {"content": base64.b64encode(b"ok").decode(),
                                                     "encoding": "base64", "size": 3})
                 for i in range(3)}}
    conn = GitHubConnector(_cfg(), client=_client(routes, []),
                           ingest_cfg=IngestConfig(include_exts=[".md"],
                                                   max_files_per_source=3))
    cs = conn.fetch_changes({})
    assert len(cs.added) == 3
    assert any("达到文件数上限" in r for _, r in cs.failed)


def test_pdf_over_1mb_via_blobs_api():
    """终审 I3：Blobs API 无 Contents 1MB 上限——大 PDF 正常拉取。"""
    big_pdf = b"%PDF" + b"x" * (2 * 1024 * 1024)
    tree = {"tree": [{"path": "big.pdf", "type": "blob", "sha": "shaBig", "size": len(big_pdf)}],
            "truncated": False}
    routes = {("GET", "/git/trees/main"): (200, tree),
              ("GET", "/git/blobs/shaBig"): (200, {"content": base64.b64encode(big_pdf).decode(),
                                                   "encoding": "base64", "size": len(big_pdf)})}
    conn = GitHubConnector(_cfg(), client=_client(routes, []),
                           ingest_cfg=IngestConfig(include_exts=[".pdf"]))
    assert conn.fetch_all()[0].binary == big_pdf


# ---------- 终审 C1：工厂必须传 ingest_cfg ----------

def test_factory_passes_ingest_cfg_to_github(tmp_path):
    from ragdb.config import Settings
    from ragdb.ingest.factory import build_connectors

    cfg = SourceConfig(name="docs", type="github", repo="o/r",
                       include_exts=[".md", ".pdf"])
    items = build_connectors(Settings(sources=[cfg]))
    assert items[0][1]._ingest.include_exts == [".md", ".pdf"]  # 非默认 md-only
