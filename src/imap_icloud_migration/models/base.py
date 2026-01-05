"""Base Pydantic model configuration."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class AppModel(BaseModel):
    """Base model with strict-ish, safe defaults."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        validate_default=True,
        validate_assignment=True,
    )
