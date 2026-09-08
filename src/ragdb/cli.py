"""CLI：serve / sync / search / rebuild / status；写者协调（serve 存活则转调）。"""

from __future__ import annotations

import argparse
import fcntl
import json
import sys
from dataclasses import asdict, is_dataclass

import httpx

from ragdb.config import Settings
from ragdb.core import Core


def _build_core(config_path=None) -> Core:
    return Core.from_settings(Settings.load(config_path))


def _print_report(report) -> None:
    if is_dataclass(report):
        report = asdict(report)
    print(json.dumps(report, ensure_ascii=False, indent=2))


def _coordinated_sync(core: Core, full: bool) -> int:
    base = f"http://127.0.0.1:{core.settings.port}"
    try:
        if httpx.get(f"{base}/api/v1/health", timeout=1.0).status_code == 200:
            resp = httpx.post(f"{base}/api/v1/sync", json={"full": full},
                              timeout=300.0)
            _print_report(resp.json())
            return 0
    except httpx.HTTPError:
        pass  # serve 不在，走本地写
    lock_path = core.settings.data_dir / "ragdb.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("写入权被其它进程持有（serve 正在运行？）", file=sys.stderr)
            return 1
        report = core.engine.run(full=full)
        _print_report(report)
        return 0


def _cmd_serve(core: Core) -> int:
    from ragdb.api.app import run_serve

    run_serve(core)
    return 0


def _cmd_sync(core: Core) -> int:
    return _coordinated_sync(core, full=False)


def _cmd_rebuild(core: Core) -> int:
    return _coordinated_sync(core, full=True)


def _cmd_search(core: Core, query: str, top_k: int | None = None) -> int:
    results = core.retriever.search(query, top_k=top_k)
    if not results:
        print("未找到相关内容。")
        return 0
    for r in results:
        kind = "整篇" if r.whole_note else "片段"
        print(f"== {r.source_id}（{r.title}）[{kind}] 相关度 {r.score_rerank:.3f}")
        for s in r.snippets:
            print(s)
        print()
    return 0


def _cmd_status(core: Core) -> int:
    base = f"http://127.0.0.1:{core.settings.port}"
    try:
        resp = httpx.get(f"{base}/api/v1/health", timeout=1.0)
        print(json.dumps(resp.json(), ensure_ascii=False, indent=2))
        return 0
    except httpx.HTTPError:
        print("serve 未运行（本地库信息：）")
        print(json.dumps({"note_count": len(core.state.get_all()),
                          "last_sync_at": core.state.get_meta("last_sync_at")},
                         ensure_ascii=False, indent=2))
        return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ragdb", description="个人 RAG 数据库")
    parser.add_argument("--config", type=str, default=None,
                        help="ragdb.toml 路径（默认：./ragdb.toml 或内置默认值）")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("serve", help="常驻服务（FastAPI + 后台同步循环）")
    sub.add_parser("sync", help="增量同步")
    sub.add_parser("rebuild", help="全量重建")
    p_search = sub.add_parser("search", help="命令行检索")
    p_search.add_argument("query")
    p_search.add_argument("--top-k", type=int, default=None, dest="top_k",
                          help="返回条数上限（默认取配置 top_k）")
    sub.add_parser("status", help="运行状态")

    args = parser.parse_args(argv)
    core = _build_core(args.config)
    if args.cmd == "serve":
        return _cmd_serve(core)
    if args.cmd == "sync":
        return _cmd_sync(core)
    if args.cmd == "rebuild":
        return _cmd_rebuild(core)
    if args.cmd == "search":
        return _cmd_search(core, args.query, top_k=args.top_k)
    if args.cmd == "status":
        return _cmd_status(core)
    return 1
