"""FastAPI composition root."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from novelforge import __version__
from novelforge.api.routes import chapters, stories
from novelforge.api.state import close_all_engines
from novelforge.core.exceptions import GenerationRejected, WorkflowError
from novelforge.dashboard.api import router as dashboard_router
from novelforge.workspace.api import router as workspace_router


@asynccontextmanager
async def lifespan(_app: FastAPI):
    yield
    close_all_engines()


app = FastAPI(title="NovelForge", version=__version__, lifespan=lifespan)
app.include_router(stories.router)
app.include_router(chapters.router)
app.include_router(dashboard_router)
app.include_router(workspace_router)


dashboard_static = Path(__file__).parent.parent / "dashboard" / "static"
if dashboard_static.exists():
    app.mount("/static", StaticFiles(directory=str(dashboard_static)), name="static")

workspace_static = Path(__file__).parent.parent / "workspace" / "static"
if workspace_static.exists():
    app.mount(
        "/workspace-static",
        StaticFiles(directory=str(workspace_static)),
        name="workspace-static",
    )


@app.get("/")
def root() -> dict[str, str]:
    return {
        "name": "NovelForge",
        "version": __version__,
        "docs": "/docs",
        "workspace": "/workspace/",
        "dashboard": "/dashboard/",
    }


@app.exception_handler(GenerationRejected)
async def generation_rejected_handler(
    request: Request,
    exc: GenerationRejected,
) -> JSONResponse:
    report = exc.report.model_dump() if hasattr(exc.report, "model_dump") else exc.report
    return JSONResponse(
        status_code=422,
        content={"detail": str(exc), "generation_report": report},
    )


@app.exception_handler(WorkflowError)
async def workflow_error_handler(request: Request, exc: WorkflowError) -> JSONResponse:
    return JSONResponse(status_code=409, content={"detail": str(exc)})


@app.websocket("/ws/{story_id}")
async def websocket_progress(websocket: WebSocket, story_id: str) -> None:
    """Reserve a progress channel for a future external worker."""
    await websocket.accept()
    await websocket.send_json({"story_id": story_id, "message": "No background job is running."})
    await websocket.close()
