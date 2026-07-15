"""Crash-safe CreamAPI-style patch engine and helpers."""

from .engine import (
    PatchApplyResult,
    PatchEngine,
    PatchError,
    PatchRestoreReadiness,
    parse_appinfo_document,
    render_cream_api_ini,
)

__all__ = [
    "PatchApplyResult",
    "PatchEngine",
    "PatchError",
    "PatchRestoreReadiness",
    "parse_appinfo_document",
    "render_cream_api_ini",
]
