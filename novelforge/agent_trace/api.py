"""Routes for the standalone agent trace console."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

router = APIRouter(prefix="/agent-trace", tags=["agent-trace"])

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


@router.get("/", response_class=HTMLResponse)
async def agent_trace_page(request: Request, story_id: str = Query(default="")):
    """GET /agent-trace/ — 返回独立 Agent 跟踪控制台的 HTML 页面。"""
    return templates.TemplateResponse(request, "agent_trace.html", {"story_id": story_id})
