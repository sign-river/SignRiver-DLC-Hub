"""Restore a game to its pre-SignRiver state using cartridge-owned paths."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class RestoreOriginalError(RuntimeError):
    pass


class RestoreScope(StrEnum):
    SAFE = "safe"
    FULL = "full"


@dataclass(frozen=True, slots=True)
class RestorePreview:
    scope: RestoreScope
    tracked_dlc_ids: tuple[str, ...]
    detected_dlc_ids: tuple[str, ...]
    patch_ready: bool
    patch_reason: str = ""

    @property
    def dlc_count(self) -> int:
        return len(
            self.tracked_dlc_ids
            if self.scope is RestoreScope.SAFE
            else self.detected_dlc_ids
        )


@dataclass(frozen=True, slots=True)
class RestoreResult:
    scope: RestoreScope
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

    def preview(
        self, game_root: Path, scope: RestoreScope, catalog_entries=()
    ) -> RestorePreview:
        tracked = tuple(
            sorted({receipt.dlc_id for receipt in self.repository.active(self.game_id)})
        ) if self.repository is not None else ()
        detected = tuple(
            sorted(self.cartridge.discover_installed_dlc(game_root, catalog_entries))
        )
        patch = self.patch_engine.inspect_original_restore(game_root)
        return RestorePreview(
            scope=scope,
            tracked_dlc_ids=tracked,
            detected_dlc_ids=detected,
            patch_ready=patch.ready,
            patch_reason=patch.reason,
        )

    def restore(
        self, game_root: Path, scope: RestoreScope, catalog_entries=()
    ) -> RestoreResult:
        preview = self.preview(game_root, scope, catalog_entries)
        if not preview.patch_ready:
            raise RestoreOriginalError(preview.patch_reason)
        restored: list[str] = []
        failures: list[str] = []
        if scope is RestoreScope.SAFE:
            for dlc_id in preview.tracked_dlc_ids:
                try:
                    self.install_service.uninstall(self.game_id, dlc_id, game_root)
                    restored.append(dlc_id)
                except Exception as error:
                    failures.append(f"DLC {dlc_id}：{error}")
        else:
            for dlc_id in preview.detected_dlc_ids:
                try:
                    self.cartridge.remove_installed_dlc(game_root, dlc_id)
                    if self.repository is not None:
                        receipt = self.repository.find_active(self.game_id, dlc_id)
                        if receipt is not None:
                            self.repository.mark_uninstalled(
                                receipt.transaction_id, restore_previous=False
                            )
                    restored.append(dlc_id)
                except Exception as error:
                    failures.append(f"DLC {dlc_id}：{error}")
        try:
            patch_files = self.patch_engine.restore_original(game_root)
        except Exception as error:
            failures.append(f"补丁恢复：{error}")
            patch_files = ()
        return RestoreResult(
            scope=scope,
            restored_dlc_ids=tuple(restored),
            patch_files=tuple(patch_files),
            failures=tuple(failures),
        )


__all__ = [
    "OriginalStateRestoreService",
    "RestoreOriginalError",
    "RestorePreview",
    "RestoreResult",
    "RestoreScope",
]
