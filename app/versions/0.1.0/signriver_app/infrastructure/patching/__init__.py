"""Crash-safe CreamAPI-style patch engine and helpers."""

from .original_library import (
    OriginalLibraryEntry,
    OriginalLibraryError,
    OriginalLibraryVault,
)
from .repair_journal import RepairJournal, RepairJournalState
from .engine import (
    PatchApplyResult,
    PatchEngine,
    PatchError,
    PatchRestoreReadiness,
    looks_like_native_library,
    parse_appinfo_document,
    render_cream_api_ini,
    render_patch_config,
    render_smoke_api_config,
)

__all__ = [
    "OriginalLibraryEntry",
    "OriginalLibraryError",
    "OriginalLibraryVault",
    "RepairJournal",
    "RepairJournalState",
    "PatchApplyResult",
    "PatchEngine",
    "PatchError",
    "PatchRestoreReadiness",
    "looks_like_native_library",
    "parse_appinfo_document",
    "render_cream_api_ini",
    "render_patch_config",
    "render_smoke_api_config",
]
