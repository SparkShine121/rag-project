"""GitHubConnector 测试：httpx.MockTransport 模拟 GitHub API，零网络。"""

import base64

import httpx
import pytest

from ragdb.config import SourceConfig
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
    """routes: (method, path_regex) -> (status, json)；记录所有调用。"""

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
    b64 = base64.b64encode(CONTENT_A.encode()).decode()
    return {
        ("GET", "/git/trees/main"): (200, tree),
        ("GET", "/contents/docs/a.md"): (200, {"content": b64, "encoding": "base64",
                                               "html_url": "https://github.com/o/r/blob/main/docs/a.md"}),
        ("GET", "/contents/README.md"): (200, {"content": base64.b64encode("说明".encode()).decode(),
                                               "encoding": "base64", "html_url": ""}),
    }


def test_fetch_all_only_md_and_decoded():
    calls: list = []
    conn = GitHubConnector(_cfg(), client=_client(_routes(), calls))
    docs = conn.fetch_all()
    assert sorted(d.source_id for d in docs) == ["README.md", "docs/a.md"]
    a = next(d for d in docs if d.source_id == "docs/a.md")
    assert a.content == CONTENT_A
    assert a.hash_override == "shaA" and a.content_hash == "shaA"
    assert a.metadata["html_url"].endswith("docs/a.md")
    assert a.source_type == "github"


def test_fetch_all_without_token_has_no_auth_header():
    calls: list = []
    GitHubConnector(_cfg(), client=_client(_routes(), calls)).fetch_all()
    assert all("authorization" not in h.headers for h in calls)


def test_fetch_all_with_token_sends_bearer():
    calls: list = []
    GitHubConnector(_cfg(), token="tok123", client=_client(_routes(), calls)).fetch_all()
    assert all(h.headers.get("authorization") == "Bearer tok123" for h in calls)


def test_fetch_changes_four_classes_and_skip_unchanged_download():
    calls: list = []
    tree = {"tree": [{"path": "README.md", "type": "blob", "sha": "shaR", "size": 5}],
            "truncated": False}  # docs/a.md 已从仓库消失
    conn = GitHubConnector(_cfg(), client=_client(_routes(tree), calls))
    known = {"README.md": (0.0, 5, "shaR"), "docs/a.md": (0.0, 10, "shaA")}
    cs = conn.fetch_changes(known)
    assert cs.unchanged == 1 and cs.deleted == ["docs/a.md"]
    assert cs.added == [] and cs.modified == [] and cs.moved == []
    # 无变更文件 → 除 tree 外没有任何 contents 请求
    assert sum(1 for c in calls if "/contents/" in c.url.path) == 0


def test_fetch_changes_modified_file_downloaded():
    calls: list = []
    tree = {"tree": [{"path": "README.md", "type": "blob", "sha": "shaR2", "size": 6}],
            "truncated": False}
    conn = GitHubConnector(_cfg(), client=_client(_routes(tree), calls))
    cs = conn.fetch_changes({"README.md": (0.0, 5, "shaR")})
    assert [d.source_id for d in cs.modified] == ["README.md"]
    assert cs.modified[0].content_hash == "shaR2"


def test_fetch_changes_moved_detected_via_blob_sha():
    tree = {"tree": [{"path": "new/位置.md", "type": "blob", "sha": "shaA", "size": 10}],
            "truncated": False}
    calls: list = []
    b64 = base64.b64encode(CONTENT_A.encode()).decode()
    routes = {("GET", "/git/trees/main"): (200, tree),
              ("GET", "/contents/new/位置.md"): (200, {"content": b64,
                                                      "encoding": "base64",
                                                      "html_url": ""})}
    conn = GitHubConnector(_cfg(), client=_client(routes, calls))
    cs = conn.fetch_changes({"docs/a.md": (0.0, 10, "shaA")})
    assert cs.moved[0][0] == "docs/a.md"
    assert cs.moved[0][1].source_id == "new/位置.md"


def test_repo_not_found_or_private_hint():
    calls: list = []
    conn = GitHubConnector(_cfg(), client=_client({}, calls))
    with pytest.raises(ValueError, match="私有|token|不存在"):
        conn.fetch_all()


def test_auth_failure_hint():
    calls: list = []
    routes = {("GET", "/git/trees/main"): (401, {"message": "Bad credentials"})}
    conn = GitHubConnector(_cfg(), client=_client(routes, calls))
    with pytest.raises(ValueError, match="认证|token"):
        conn.fetch_all()


def test_truncated_tree_rejected():
    calls: list = []
    tree = dict(TREE, truncated=True)
    conn = GitHubConnector(_cfg(), client=_client(_routes(tree), calls))
    with pytest.raises(ValueError, match="截断"):
        conn.fetch_all()


def test_title_from_h1_not_frontmatter():
    calls: list = []
    b64 = base64.b64encode("---\n# 假标题\ntags: [x]\n---\n# 真标题\n正文".encode()).decode()
    tree = {"tree": [{"path": "t.md", "type": "blob", "sha": "shaT", "size": 5}],
            "truncated": False}
    routes = {("GET", "/git/trees/main"): (200, tree),
              ("GET", "/contents/t.md"): (200, {"content": b64, "encoding": "base64",
                                                "html_url": ""})}
    conn = GitHubConnector(_cfg(), client=_client(routes, calls))
    doc = conn.fetch_all()[0]
    assert doc.title == "真标题"


def test_rate_limit_message_distinguishes_403_and_429():
    """终审 I2：匿名 60 次/小时的 403 限流不得误报为认证失败。"""
    routes403 = {("GET", "/git/trees/main"): (403, {"message": "rate limit"})}
    conn = GitHubConnector(_cfg(), client=_client(routes403, []))
    with pytest.raises(ValueError, match="认证/权限|限流"):
        conn.fetch_all()
    routes429 = {("GET", "/git/trees/main"): (429, {"message": "too many"})}
    conn = GitHubConnector(_cfg(), client=_client(routes429, []))
    with pytest.raises(ValueError, match="限流"):
        conn.fetch_all()


def test_oversized_md_rejected_loudly():
    """终审 I4：>1MB 文件 Contents API 返回 encoding=none/空内容，必须显式报错。"""
    routes = {("GET", "/git/trees/main"): (200, {"tree": [
        {"path": "big.md", "type": "blob", "sha": "s", "size": 2_000_000}],
        "truncated": False}),
        ("GET", "/contents/big.md"): (200, {"content": "", "encoding": "none",
                                            "html_url": ""})}
    conn = GitHubConnector(_cfg(), client=_client(routes, []))
    with pytest.raises(ValueError, match="过大|1MB"):
        conn.fetch_all()


def test_empty_md_does_not_block_source():
    """重审 N1：0 字节 .md（encoding=none）不应被误判过大，应产出空文档。"""
    routes = {("GET", "/git/trees/main"): (200, {"tree": [
        {"path": "empty.md", "type": "blob", "sha": "s0", "size": 0}],
        "truncated": False}),
        ("GET", "/contents/empty.md"): (200, {"content": "", "encoding": "none",
                                              "size": 0, "html_url": ""})}
    conn = GitHubConnector(_cfg(), client=_client(routes, []))
    docs = conn.fetch_all()
    assert len(docs) == 1 and docs[0].content == ""  # 空文档 → 引擎按 0 块处理
