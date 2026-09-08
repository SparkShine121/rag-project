"""HTTP 薄壳：REST 五端点 + /mcp + serve 写锁 + 后台同步循环。业务逻辑全在 Core。"""

from __future__ import annotations

import asyncio
import contextlib
import fcntl
import logging
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import asdict

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from ragdb.mcp_server import build_mcp

logger = logging.getLogger("ragdb.api")


class SearchRequest(BaseModel):
    query: str
    top_k: int | None = Field(default=None, ge=1, le=50)
    folder: str | None = None
    tags: list[str] | None = None

    @field_validator("query")
    @classmethod
    def _query_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("查询词不能为空")
        return v


class SyncRequest(BaseModel):
    full: bool = False


def _error(code: str, message: str, status: int) -> JSONResponse:
    return JSONResponse(status_code=status,
                        content={"error": {"code": code, "message": message}})


def _health_payload(core) -> dict:
    try:
        note_count = len(core.state.get_all())
        db_ok = True
        last_sync = core.state.get_meta("last_sync_at")
    except Exception:  # noqa: BLE001 —— health 必须反映而非传播故障
        note_count, db_ok, last_sync = 0, False, None
    models_loaded = core.hub._embedder is not None
    return {"status": "ok" if db_ok else "degraded", "db_ok": db_ok,
            "models_loaded": models_loaded, "note_count": note_count,
            "last_sync_at": last_sync}


def create_app(core) -> FastAPI:
    mcp_app = build_mcp(core).streamable_http_app()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # serve 进程持写锁：单写者由锁保证，CLI 撞锁即明确拒绝
        core.settings.data_dir.mkdir(parents=True, exist_ok=True)
        # 锁需横跨整个 lifespan 持有，不能用 with 上下文管理器
        lock_file = open(core.settings.data_dir / "ragdb.lock", "w")  # noqa: SIM115, ASYNC230
        try:
            fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            lock_file.close()
            raise RuntimeError(
                "ragdb.lock 已被占用：另一个 serve/CLI 写进程正在运行"
            ) from None
        async with AsyncExitStack() as stack:
            # Mount 不传播子应用 lifespan：手动启动 MCP session manager
            await stack.enter_async_context(
                mcp_app.router.lifespan_context(mcp_app)
            )
            task = None
            if core.settings.interval_secs > 0:

                async def loop():
                    while True:
                        try:
                            # 线程池执行：长同步不阻塞事件循环（health 保持响应）
                            await asyncio.to_thread(core.engine.run)
                        except Exception:  # 循环不退出
                            logger.exception("后台同步失败")
                        await asyncio.sleep(core.settings.interval_secs)

                task = asyncio.create_task(loop())
            try:
                yield
            finally:
                if task:
                    task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await task
                fcntl.flock(lock_file, fcntl.LOCK_UN)
                lock_file.close()

    app = FastAPI(title="ragdb", version="0.1.0", lifespan=lifespan)

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        return _error(str(exc.detail), str(exc.detail), exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        return _error("validation_error", str(exc.errors()[:3]), 422)

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception):
        return _error("internal_error", str(exc), 500)

    @app.post("/api/v1/search")
    async def search(req: SearchRequest):
        results = core.retriever.search(
            req.query, top_k=req.top_k, folder=req.folder, tags=req.tags
        )
        return [asdict(r) for r in results]

    @app.get("/api/v1/notes")
    async def notes(folder: str | None = None, tag: str | None = None):
        return core.store.list_notes(folder=folder, tag=tag)

    @app.get("/api/v1/notes/{source_id:path}")
    async def note_detail(source_id: str):
        hits = core.store.fetch_by_source(source_id)
        if not hits:
            raise HTTPException(status_code=404, detail="not_found")
        return {"source_id": source_id, "title": hits[0].title,
                "tags": hits[0].tags,
                "content": "\n\n".join(h.content for h in hits)}

    @app.post("/api/v1/sync")
    async def sync(req: SyncRequest):
        return asdict(core.engine.run(full=req.full))

    @app.get("/api/v1/health")
    async def health():
        return _health_payload(core)

    # 挂载顺序：先注册的 /api 路由优先命中，"/" 兜底交给 MCP（其内部路由为 /mcp）
    app.mount("/", mcp_app)
    return app


def run_serve(core) -> None:
    import uvicorn

    uvicorn.run(create_app(core), host="127.0.0.1", port=core.settings.port)
