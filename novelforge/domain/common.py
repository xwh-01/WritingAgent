"""Shared domain primitives with no infrastructure dependencies."""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256

from pydantic import BaseModel, ConfigDict


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def content_digest(content: str) -> str:
    """Return a stable full digest for provenance checks."""
    return sha256(content.encode("utf-8")).hexdigest()


class DomainModel(BaseModel):
    """Base for domain values that validates every later assignment."""

    model_config = ConfigDict(validate_assignment=True, str_strip_whitespace=True)
