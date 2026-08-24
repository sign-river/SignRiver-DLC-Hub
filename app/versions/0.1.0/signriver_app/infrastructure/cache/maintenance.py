"""Plan-first cleanup for unreferenced DLC cache content."""

from __future__ import annotations

import os
import shutil
import stat
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class CacheCleanupPlan:
    paths: tuple[Path, ...]
    bytes_to_remove: int
    file_count: int


@dataclass(frozen=True, slots=True)
class CacheGameUsage:
    game_id: str
    bytes_used: int
    file_count: int


class CacheMaintenance:
    def __init__(self, cache_root: Path) -> None:
        self.cache_root = Path(cache_root).resolve()

    def usage_bytes(self) -> int:
        """Return the size of cache content owned by the application.

        The cache root may also contain development leftovers or directories
        created by another Windows account.  Those entries are neither part of
        the runtime cache nor a reason for the settings page to fail.  Walk only
        the documented cache namespaces and ignore individual paths that cannot
        be inspected.
        """
        total = sum(
            self._directory_usage(self.cache_root / name)
            for name in ("downloads", "packages", "quarantine")
        )

        # Module updates briefly live directly below cache/ before the launcher
        # installs and removes them.  Include only that known file family; do
        # not count arbitrary root-level files left by tests or users.
        try:
            root_entries = tuple(self.cache_root.iterdir())
        except OSError:
            root_entries = ()
        for path in root_entries:
            if path.name.startswith("module-") and path.name.endswith(
                (".zip", ".zip.part")
            ):
                total += self._regular_file_size(path)
        return total

    @classmethod
    def _directory_usage(cls, root: Path) -> int:
        total = 0
        try:
            for directory, _subdirectories, filenames in os.walk(
                root, followlinks=False, onerror=lambda _error: None
            ):
                for filename in filenames:
                    total += cls._regular_file_size(Path(directory) / filename)
        except OSError:
            # A directory can disappear or become inaccessible between walk
            # iterations.  Other cache namespaces should still be counted.
            pass
        return total

    @staticmethod
    def _regular_file_size(path: Path) -> int:
        try:
            details = path.stat(follow_symlinks=False)
        except OSError:
            return 0
        return details.st_size if stat.S_ISREG(details.st_mode) else 0

    def plan(self, *, protected_paths=(), active_task_ids=()) -> CacheCleanupPlan:
        protected = {Path(path).resolve(strict=False) for path in protected_paths}
        candidates: list[Path] = []
        packages = self.cache_root / "packages"
        if packages.is_dir():
            package_directories = {path.parent for path in packages.rglob("*") if path.is_file()}
            candidates.extend(
                directory for directory in package_directories
                if not any(self._is_within(path, directory) for path in protected)
            )
        quarantine = self.cache_root / "quarantine"
        if quarantine.is_dir():
            candidates.extend(path for path in quarantine.iterdir())
        downloads = self.cache_root / "downloads"
        active_parts = {f"{task_id}.part" for task_id in active_task_ids}
        if downloads.is_dir():
            candidates.extend(
                path for path in downloads.rglob("*.part")
                if path.name not in active_parts
            )
        files = [
            file for candidate in candidates
            for file in ([candidate] if candidate.is_file() else candidate.rglob("*"))
            if file.is_file()
        ]
        return CacheCleanupPlan(
            tuple(candidates),
            sum(path.stat().st_size for path in files),
            len(files),
        )

    def plan_full_cleanup(self) -> CacheCleanupPlan:
        """Plan deletion of every application-owned, re-downloadable cache file.

        The cache root may be shared with the launcher, so this deliberately
        limits deletion to documented download namespaces and launcher module
        archives.  It never accepts arbitrary paths or reaches game/data roots.
        """
        files: list[Path] = []
        for name in ("downloads", "packages", "quarantine"):
            files.extend(self._files_in(self.cache_root / name))
        try:
            root_entries = tuple(self.cache_root.iterdir())
        except OSError:
            root_entries = ()
        for path in root_entries:
            if (
                path.name.startswith("module-")
                and path.name.endswith((".zip", ".zip.part"))
                and self._regular_file_size(path) >= 0
            ):
                try:
                    details = path.stat(follow_symlinks=False)
                except OSError:
                    continue
                if stat.S_ISREG(details.st_mode):
                    files.append(path)
        return CacheCleanupPlan(
            tuple(files),
            sum(self._regular_file_size(path) for path in files),
            len(files),
        )

    def game_usage(self, game_id: str, snapshots=()) -> CacheGameUsage:
        """Summarize one game's readable, self-contained package cache."""
        files = self._files_in(self.cache_root / "packages" / game_id)
        return CacheGameUsage(
            game_id=game_id,
            bytes_used=sum(self._regular_file_size(path) for path in files),
            file_count=len(files),
        )

    def plan_game_cleanup(self, game_id: str, snapshots=()) -> CacheCleanupPlan:
        """Plan removal of every cache namespace owned by one game."""
        candidates = tuple(
            path for path in (
                self.cache_root / "packages" / game_id,
                self.cache_root / "quarantine" / game_id,
                self.cache_root / "downloads" / game_id,
            ) if path.exists()
        )
        files = [file for directory in candidates for file in self._files_in(directory)]
        return CacheCleanupPlan(
            candidates,
            sum(self._regular_file_size(path) for path in files),
            len(files),
        )

    def execute(self, plan: CacheCleanupPlan) -> None:
        prune_roots: list[Path] = []
        for path in plan.paths:
            resolved = Path(path).resolve(strict=False)
            if not self._is_within(resolved, self.cache_root) or resolved == self.cache_root:
                raise ValueError("cleanup path escaped cache root")
            prune_roots.append(resolved.parent)
            if resolved.is_dir():
                shutil.rmtree(resolved)
            else:
                resolved.unlink(missing_ok=True)
        for root in prune_roots:
            self._prune_empty_owned_ancestors(root)

    def _prune_empty_owned_ancestors(self, path: Path) -> None:
        """Remove now-empty child folders, never cache namespaces or other data."""
        current = Path(path)
        while current != self.cache_root and self._is_within(current, self.cache_root):
            try:
                relative = current.relative_to(self.cache_root)
            except ValueError:
                return
            # Only clean descendants of namespaces owned by this class.  Keep
            # downloads/packages/quarantine themselves so normal runtime code
            # can recreate files without needing to rebuild its root layout.
            if len(relative.parts) <= 1 or relative.parts[0] not in {
                "downloads", "packages", "quarantine",
            }:
                return
            try:
                if current.is_symlink():
                    return
                current.rmdir()
            except OSError:
                return
            current = current.parent

    @staticmethod
    def _files_in(root: Path) -> list[Path]:
        try:
            return [path for path in root.rglob("*") if path.is_file()]
        except OSError:
            return []

    @staticmethod
    def _is_within(path: Path, root: Path) -> bool:
        try:
            path.resolve(strict=False).relative_to(root.resolve(strict=False))
            return True
        except ValueError:
            return False
