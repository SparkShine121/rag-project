"""GitHub 仓库连接器：Contents API + git blob sha 增量（同 blob = 同内容，零下载判变更）。"""

from __future__ import annotations

import base64
from pathlib import Path

import httpx

from ragdb.config import IngestConfig, SourceConfig
from ragdb.ingest.changeset import build_change_set
from ragdb.ingest.connector import SourceConnector, extract_title
from ragdb.ingest.schema import ChangeSet, FileStamp, RawDocument


class GitHubConnector(SourceConnector):
    API_BASE = "https://api.github.com"

    def __init__(self, source: SourceConfig, token: str | None = None,
                 client: httpx.Client | None = None,
                 ingest_cfg: IngestConfig | None = None):
        self._cfg = source
        self._token = token
        self._client = client or httpx.Client(base_url=self.API_BASE, timeout=30.0)
        # 未传过滤配置时保持 v1.1 行为：仅索引 .md
        self._ingest = ingest_cfg or IngestConfig(include_exts=[".md"])
        self._sha_by_path: dict[str, str] = {}
        self._skipped: list[tuple[str, str]] = []

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
        if resp.status_code == 429 or (
            resp.status_code == 403
            and resp.headers.get("x-ratelimit-remaining") == "0"
        ):
            raise ValueError(
                "GitHub API 限流——匿名额度仅 60 次/小时，"
                "请在来源配置中设置 token_env 或降低同步频率"
            )
        if resp.status_code in (401, 403):
            raise ValueError(
                f"GitHub 认证/权限被拒（{resp.status_code}）——检查 token_env 指向的 "
                f"token 是否有效、是否有该仓库权限；若非认证问题则可能是限流"
                f"（匿名 60 次/小时）"
            )
        resp.raise_for_status()
        return resp.json()

    def _matching_blobs(self) -> list[dict]:
        data = self._api_get(f"/repos/{self._cfg.repo}/git/trees/{self._cfg.ref}",
                             params={"recursive": "1"})
        if data.get("truncated"):
            raise ValueError(
                f"仓库 {self._cfg.repo} 文件树过大被 GitHub 截断，超出本连接器支持范围"
            )
        exts = {e.lower() for e in self._ingest.include_exts}
        max_bytes = self._ingest.max_file_mb * 1024 * 1024
        blobs: list[dict] = []
        skipped: list[tuple[str, str]] = []
        for t in data["tree"]:
            if t.get("type") != "blob":
                continue
            path = t["path"]
            if Path(path).suffix.lower() not in exts:
                continue  # 白名单外忽略（不计入数量/大小口径）
            if t.get("size", 0) > max_bytes:
                skipped.append((path,
                                f"超过大小上限（{self._ingest.max_file_mb}MB）"))
                continue
            blobs.append(t)
        self._skipped = skipped
        return blobs

    def _current_stamps(self, blobs: list[dict]) -> dict[str, FileStamp]:
        return {t["path"]: (0.0, t.get("size", 0), t["sha"]) for t in blobs}

    def _fetch_doc(self, path: str) -> RawDocument:
        data = self._api_get(f"/repos/{self._cfg.repo}/contents/{path}",
                             params={"ref": self._cfg.ref})
        encoded = data.get("content", "")
        # >1MB 文件 Contents API 返回 encoding:"none" 且 content 为空（终审 I4）；
        # 0 字节文件同样返回空内容，但不属于过大（重审 N1）
        if (data.get("encoding") != "base64" or not encoded) and data.get("size", 1) > 0:
            raise ValueError(
                f"文件过大或无法获取内容（Contents API 对 >1MB 文件返回空内容）: {path}"
            )
        raw = base64.b64decode(encoded) if encoded else b""
        sha = self._sha_by_path.get(path, data.get("sha", ""))
        if path.lower().endswith(".pdf"):
            # PDF 是二进制：内容放 binary，不进 content 字符串
            return RawDocument(
                source_type="github", source_id=path, title=Path(path).stem,
                content="", metadata={"blob_sha": sha,
                                      "html_url": data.get("html_url", "")},
                hash_override=sha, binary=raw,
            )
        text = raw.decode("utf-8")
        return RawDocument(
            source_type="github",
            source_id=path,
            title=extract_title(text, Path(path).stem),
            content=text,
            metadata={"blob_sha": sha, "html_url": data.get("html_url", "")},
            hash_override=sha,
        )

    def fetch_all(self) -> list[RawDocument]:
        blobs = self._matching_blobs()
        self._sha_by_path = {t["path"]: t["sha"] for t in blobs}
        return [self._fetch_doc(t["path"]) for t in blobs]

    def fetch_changes(self, known: dict[str, FileStamp]) -> ChangeSet:
        blobs = self._matching_blobs()
        self._sha_by_path = {t["path"]: t["sha"] for t in blobs}
        cs = build_change_set(known, self._current_stamps(blobs), self._fetch_doc)
        cs.failed.extend(self._skipped)
        return cs
