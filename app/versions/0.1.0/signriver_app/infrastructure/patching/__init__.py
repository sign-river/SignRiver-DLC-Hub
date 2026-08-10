"""Crash-safe CreamAPI-style patch engine and helpers."""

from .engine import (
    PatchApplyResult,
    PatchEngine,
    PatchError,
    PatchRestoreReadiness,
    parse_appinfo_document,
    render_cream_api_ini,
    render_patch_config,
    render_smoke_api_config,
)

__all__ = [
    "PatchApplyResult",
    "PatchEngine",
    "PatchError",
    "PatchRestoreReadiness",
    "parse_appinfo_document",
    "render_cream_api_ini",
    "render_patch_config",
    "render_smoke_api_config",
]
