"""FastAPI routes for the story panorama dashboard."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from novelforge.api.state import get_engine
from novelforge.dashboard.data_provider import DashboardDataProvider
from novelforge.storage.repository import StoryRepository

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

templates_dir = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(templates_dir))


@router.get("/", response_class=HTMLResponse)
async def dashboard_page(request: Request, story_id: str = Query(default="")):
    """GET /dashboard/ — 返回故事全景仪表盘的 HTML 页面。"""
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "story_id": story_id,
        },
    )


@router.get("/data/{story_id}")
async def get_dashboard_data(story_id: str):
    """GET /dashboard/data/{story_id} — 返回指定故事的仪表盘汇总数据（JSON）。"""
    try:
        engine = get_engine(story_id)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=f"Story not found: {story_id}") from exc
    provider = DashboardDataProvider(engine.story)
    return JSONResponse(asdict(provider.get_all_data()))


@router.get("/stories")
async def list_story_states():
    """GET /dashboard/stories — 列出所有已保存故事的记录摘要。"""
    return {"stories": [record.__dict__ for record in StoryRepository().list_records()]}
