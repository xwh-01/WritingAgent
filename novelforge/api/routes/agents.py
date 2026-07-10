"""Agent metadata endpoints."""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/agents", tags=["agents"])


@router.get("/")
def list_agents() -> dict[str, list[str]]:
    """GET /agents/ — 返回系统中所有可用代理角色名称列表。"""
    return {
        "agents": [
            "planner",
            "writer",
            "critic",
            "editor",
            "supervisor",
            "director",
            "continuity_auditor",
            "memory_extractor",
            "context",
            "memory",
        ]
    }
