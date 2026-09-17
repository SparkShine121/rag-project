"""MCP 共享工具与服务器构建（stdio 与 /mcp 同一套）。"""

from __future__ import annotations

import logging
import threading

from mcp.server.fastmcp import FastMCP

logger = logging.getLogger("ragdb.mcp")


def start_idle_unloader(core, interval_secs: int = 60):
    """守护巡检线程：每 interval_secs 秒调用 hub.maybe_unload（TTL 空闲卸载）。

    返回 (thread, stop_event)。进程**绝不**自行退出——仅释放权重，
    stdio 连接保持存活（agent 会话安全）。
    """
    stop = threading.Event()

    def watch():
        while not stop.wait(interval_secs):
            try:
                core.hub.maybe_unload()
            except Exception:
                logger.exception("模型空闲卸载巡检失败")

    thread = threading.Thread(target=watch, daemon=True, name="ragdb-idle-unloader")
    thread.start()
    return thread, stop


def _tool_search(core, query: str, top_k: int = 5, folder: str | None = None,
                 tags: list[str] | None = None) -> str:
    if not query.strip():
        return "查询词为空，请提供要检索的内容。"
    with core.search_inflight.track():  # 与 REST 共用计数：supervised exit 的安全阀
        results = core.retriever.search(query, top_k=top_k, folder=folder, tags=tags)
    if not results:
        return "未找到相关内容。"
    blocks = []
    for r in results:
        kind = "整篇" if r.whole_note else "片段"
        blocks.append(
            f"## {r.source_id}（{r.title}）[{kind}]\n"
            f"标题链: {r.heading_path}\n相关度: {r.score_rerank:.3f}\n"
            f"{r.snippets[0]}"
        )
    return "\n\n".join(blocks)


def _tool_get_note(core, source_id: str) -> str:
    hits = core.store.fetch_by_source(source_id)
    if not hits:
        return f"未找到笔记: {source_id}"
    content = "\n\n".join(h.content for h in hits)
    tags = ",".join(hits[0].tags) or "无"
    return f"# {hits[0].title}\ntags: {tags}\n\n{content}"


def _tool_list_notes(core, folder: str | None = None,
                     tag: str | None = None) -> str:
    notes = core.store.list_notes(folder=folder, tag=tag)
    if not notes:
        return "（空）"
    return "\n".join(
        f"{n['source_id']} | {n['title']} | tags: {','.join(n['tags']) or '无'}"
        for n in notes
    )


def build_mcp(core) -> FastMCP:
    mcp = FastMCP("ragdb")

    @mcp.tool()
    def search(query: str, top_k: int = 5, folder: str | None = None,
               tags: list[str] | None = None) -> str:
        """语义检索个人知识库（只读）。返回带出处的笔记片段。"""
        return _tool_search(core, query, top_k=top_k, folder=folder, tags=tags)

    @mcp.tool()
    def get_note(source_id: str) -> str:
        """按路径读取整篇笔记全文（只读）。"""
        return _tool_get_note(core, source_id)

    @mcp.tool()
    def list_notes(folder: str | None = None, tag: str | None = None) -> str:
        """列出知识库笔记清单，可按目录前缀或 tag 过滤（只读）。"""
        return _tool_list_notes(core, folder=folder, tag=tag)

    return mcp


def main() -> None:
    """console script `ragdb-mcp` 入口：stdio 传输，只读进程。"""
    from ragdb.config import Settings
    from ragdb.core import Core

    core = Core.from_settings(Settings.load())
    start_idle_unloader(core)  # TTL 空闲卸载巡检（v1.3.1）：进程保持存活，仅释放权重
    build_mcp(core).run(transport="stdio")
