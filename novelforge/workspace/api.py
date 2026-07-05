"""FastAPI routes for the interactive writing workspace."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

router = APIRouter(prefix="/workspace", tags=["workspace"])

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


@router.get("/", response_class=HTMLResponse)
async def workspace_page(request: Request, story_id: str = Query(default="")):
    return templates.TemplateResponse(request, "workspace.html", {"story_id": story_id})
