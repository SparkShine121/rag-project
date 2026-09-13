"""GitHub 仓库连接器：Contents API + git blob sha 增量（同 blob = 同内容，零下载判变更）。"""

from __future__ import annotations

import base64
from pathlib import Path

import httpx

from ragdb.config import SourceConfig
from ragdb.ingest.changeset import build_change_set
from ragdb.ingest.connector import SourceConnector, extract_title
from ragdb.ingest.schema import ChangeSet, FileStamp, RawDocument


class GitHubConnector(SourceConnector):
    API_BASE = "https://api.github.com"

    def __init__(self, source: SourceConfig, token: str | None = None,
                 client: httpx.Client | None = None):
        self._cfg = source
        self._token = token
        self._client = client or httpx.Client(base_url=self.API_BASE, timeout=30.0)
        self._sha_by_path: dict[str, str] = {}

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/vnd.github+json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    def _api_get(self, path: str, params: dict | None = None) -> dict:
        resp = self._client.get(path, params=params, headers=self._headers())
        if resp.status_code == 404:
            raise ValueError(
                f"GitHub 仓库或 ref 不存在（或为私有仓库而未配置 token）: "
                f"{self._cfg.repo}@{self._cfg.ref}"
            )
        if resp.status_code in (401, 403):
            raise ValueError(
                f"GitHub 认证失败（{resp.status_code}）——检查 token_env 指向的 token"
            )
        resp.raise_for_status()
        return resp.json()

    def _md_blobs(self) -> list[dict]:
        data = self._api_get(f"/repos/{self._cfg.repo}/git/trees/{self._cfg.ref}",
                             params={"recursive": "1"})
        if data.get("truncated"):
            raise ValueError(
                f"仓库 {self._cfg.repo} 文件树过大被 GitHub 截断，超出本连接器支持范围"
            )
        return [t for t in data["tree"]
                if t.get("type") == "blob" and t["path"].endswith(".md")]

    def _current_stamps(self, blobs: list[dict]) -> dict[str, FileStamp]:
        return {t["path"]: (0.0, t.get("size", 0), t["sha"]) for t in blobs}

    def _fetch_doc(self, path: str) -> RawDocument:
        data = self._api_get(f"/repos/{self._cfg.repo}/contents/{path}",
                             params={"ref": self._cfg.ref})
        encoded = data.get("content", "")
        text = (base64.b64decode(encoded).decode("utf-8")
                if data.get("encoding") == "base64" else encoded)
        sha = self._sha_by_path.get(path, data.get("sha", ""))
        return RawDocument(
            source_type="github",
            source_id=path,
            title=extract_title(text, Path(path).stem),
            content=text,
            metadata={"blob_sha": sha, "html_url": data.get("html_url", "")},
            hash_override=sha,
        )

    def fetch_all(self) -> list[RawDocument]:
        blobs = self._md_blobs()
        self._sha_by_path = {t["path"]: t["sha"] for t in blobs}
        return [self._fetch_doc(t["path"]) for t in blobs]

    def fetch_changes(self, known: dict[str, FileStamp]) -> ChangeSet:
        blobs = self._md_blobs()
        self._sha_by_path = {t["path"]: t["sha"] for t in blobs}
        return build_change_set(known, self._current_stamps(blobs), self._fetch_doc)
