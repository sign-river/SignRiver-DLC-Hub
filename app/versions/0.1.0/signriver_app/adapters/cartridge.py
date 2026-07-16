"""Game cartridge contract loaded by the desktop shell.

A cartridge owns everything that varies between games: local discovery,
remote resources, patch layout and DLC installation behaviour. The shell is
therefore a console; adding a game means registering another cartridge rather
than adding another set of conditionals to ``app_entry.py``.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from ..domain import PatchBundle, PatchProfile
from .protocol import GameAdapter


@runtime_checkable
class GameCartridge(Protocol):
    @property
    def cartridge_id(self) -> str: ...
    @property
    def selection_name(self) -> str: ...
    @property
    def platform_name(self) -> str: ...
    @property
    def store_app_id(self) -> str: ...
    @property
    def release_tag(self) -> str: ...
    @property
    def dlc_relative_dir(self) -> str: ...
    @property
    def adapter(self) -> GameAdapter: ...
    @property
    def patch_profile(self) -> PatchProfile: ...
    def patch_task_roles(self, bundle: PatchBundle) -> Mapping[str, str]: ...
    def create_catalog(self) -> Any: ...
    def create_install_engine(self, data_root: Path) -> Any: ...
    def inspect_package(
        self, path: Path, *, asset_name: str | None = None
    ) -> Any: ...
    def discover_installed_dlc(
        self, game_root: Path, catalog_entries=()
    ) -> dict[str, Path]: ...
    def remove_installed_dlc(self, game_root: Path, dlc_id: str) -> Path: ...


__all__ = ["GameCartridge"]
