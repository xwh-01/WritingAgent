"""Read-only dashboard HTTP adapter."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from novelforge.api.state import get_engine
from novelforge.dashboard.data_provider import DashboardDataProvider
from novelforge.orchestrator.engine import NovelForgeEngine

router = APIRouter(prefix="/dashboard", tags=["dashboard"])
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


@router.get("/", response_class=HTMLResponse)
async def dashboard_page(request: Request, story_id: str = Query(default="")):
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {"story_id": story_id},
    )


@router.get("/data/{story_id}")
def dashboard_data(story_id: str) -> dict:
    try:
        story = get_engine(story_id).current_story
    except Exception as exc:
        raise HTTPException(status_code=404, detail="Story not found.") from exc
    return asdict(DashboardDataProvider(story).get_all_data())


@router.get("/stories")
def list_stories() -> dict:
    records = NovelForgeEngine().repository.list_records()
    return {"stories": [record.__dict__ for record in records]}
