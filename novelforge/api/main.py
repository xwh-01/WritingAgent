"""FastAPI entrypoint for NovelForge."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, WebSocket
from fastapi.staticfiles import StaticFiles

from novelforge import __version__
from novelforge.api.routes import agents, chapters, stories
from novelforge.dashboard.api import router as dashboard_router
from novelforge.workspace.api import router as workspace_router

app = FastAPI(title="NovelForge", version=__version__)
app.include_router(stories.router)
app.include_router(chapters.router)
app.include_router(agents.router)
app.include_router(dashboard_router)
app.include_router(workspace_router)

dashboard_static = Path(__file__).parent.parent / "dashboard" / "static"
if dashboard_static.exists():
    app.mount("/static", StaticFiles(directory=str(dashboard_static)), name="static")

workspace_static = Path(__file__).parent.parent / "workspace" / "static"
if workspace_static.exists():
    app.mount("/workspace-static", StaticFiles(directory=str(workspace_static)), name="workspace-static")


@app.get("/")
def root() -> dict[str, str]:
    return {
        "name": "NovelForge",
        "version": __version__,
        "docs": "/docs",
        "workspace": "/workspace/",
        "dashboard": "/dashboard/",
    }


@app.websocket("/ws/{story_id}")
async def websocket_progress(websocket: WebSocket, story_id: str) -> None:
    await websocket.accept()
    await websocket.send_json({"story_id": story_id, "message": "WebSocket progress stream reserved."})
    await websocket.close()
