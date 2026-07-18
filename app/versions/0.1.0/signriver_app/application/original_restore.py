"""Restore a game to its pre-SignRiver state using cartridge-owned paths."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


class RestoreOriginalError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class RestorePreview:
    tracked_dlc_ids: tuple[str, ...]
    patch_ready: bool
    patch_reason: str = ""

    @property
    def dlc_count(self) -> int:
        return len(self.tracked_dlc_ids)


@dataclass(frozen=True, slots=True)
class RestoreResult:
    restored_dlc_ids: tuple[str, ...]
    patch_files: tuple[str, ...]
    failures: tuple[str, ...]


class OriginalStateRestoreService:
    def __init__(self, cartridge, patch_engine, install_service, repository) -> None:
        self.cartridge = cartridge
        self.patch_engine = patch_engine
        self.install_service = install_service
        self.repository = repository
        self.game_id = cartridge.adapter.descriptor.game_id

    def preview(self, game_root: Path) -> RestorePreview:
        tracked = tuple(
            sorted({receipt.dlc_id for receipt in self.repository.active(self.game_id)})
        ) if self.repository is not None else ()
        patch = self.patch_engine.inspect_original_restore(game_root)
        return RestorePreview(
            tracked_dlc_ids=tracked,
            patch_ready=patch.ready,
            patch_reason=patch.reason,
        )

    def restore(self, game_root: Path) -> RestoreResult:
        """Undo only installations backed by this application's receipts."""
        preview = self.preview(game_root)
        if not preview.patch_ready:
            raise RestoreOriginalError(preview.patch_reason)
        restored: list[str] = []
        failures: list[str] = []
        for dlc_id in preview.tracked_dlc_ids:
            try:
                self.install_service.uninstall(self.game_id, dlc_id, game_root)
                restored.append(dlc_id)
            except Exception as error:
                failures.append(f"DLC {dlc_id}：{error}")
        try:
            patch_files = self.patch_engine.restore_original(game_root)
        except Exception as error:
            failures.append(f"补丁恢复：{error}")
            patch_files = ()
        return RestoreResult(
            restored_dlc_ids=tuple(restored),
            patch_files=tuple(patch_files),
            failures=tuple(failures),
        )


__all__ = [
    "OriginalStateRestoreService",
    "RestoreOriginalError",
    "RestorePreview",
    "RestoreResult",
]
