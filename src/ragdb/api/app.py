"""HTTP 薄壳：REST 五端点 + /mcp 挂载 + 后台同步循环。业务逻辑全在 Core。"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import asdict

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from ragdb.mcp_server import build_mcp


class SearchRequest(BaseModel):
    query: str
    top_k: int | None = Field(default=None, ge=1, le=50)
    folder: str | None = None
    tags: list[str] | None = None


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
    app = FastAPI(title="ragdb", version="0.1.0")
    app.mount("/mcp", build_mcp(core).streamable_http_app())

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

    @app.on_event("startup")
    async def start_sync_loop():
        if core.settings.interval_secs <= 0:
            return

        async def loop():
            while True:
                try:
                    core.engine.run()
                except Exception:  # 循环不退出，故障进日志
                    logging.getLogger("ragdb.api").exception("后台同步失败")
                await asyncio.sleep(core.settings.interval_secs)

        app.state.sync_task = asyncio.create_task(loop())

    @app.on_event("shutdown")
    async def stop_sync_loop():
        task = getattr(app.state, "sync_task", None)
        if task:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    return app


def run_serve(core) -> None:
    import uvicorn

    uvicorn.run(create_app(core), host="127.0.0.1", port=core.settings.port)
