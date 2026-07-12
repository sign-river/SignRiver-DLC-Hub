"""Plan-first cleanup for unreferenced DLC cache content."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class CacheCleanupPlan:
    paths: tuple[Path, ...]
    bytes_to_remove: int
    file_count: int


class CacheMaintenance:
    def __init__(self, cache_root: Path) -> None:
        self.cache_root = Path(cache_root).resolve()

    def usage_bytes(self) -> int:
        return sum(
            path.stat().st_size for path in self.cache_root.rglob("*")
            if path.is_file()
        ) if self.cache_root.exists() else 0

    def plan(self, *, protected_paths=(), active_task_ids=()) -> CacheCleanupPlan:
        protected = {Path(path).resolve(strict=False) for path in protected_paths}
        candidates: list[Path] = []
        packages = self.cache_root / "packages"
        if packages.is_dir():
            for directory in packages.iterdir():
                if not directory.is_dir():
                    continue
                if not any(self._is_within(path, directory) for path in protected):
                    candidates.append(directory)
        quarantine = self.cache_root / "quarantine"
        if quarantine.is_dir():
            candidates.extend(path for path in quarantine.iterdir())
        downloads = self.cache_root / "downloads"
        active_parts = {f"{task_id}.part" for task_id in active_task_ids}
        if downloads.is_dir():
            candidates.extend(
                path for path in downloads.glob("*.part")
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

    def execute(self, plan: CacheCleanupPlan) -> None:
        for path in plan.paths:
            resolved = Path(path).resolve(strict=False)
            if not self._is_within(resolved, self.cache_root) or resolved == self.cache_root:
                raise ValueError("cleanup path escaped cache root")
            if resolved.is_dir():
                shutil.rmtree(resolved)
            else:
                resolved.unlink(missing_ok=True)

    @staticmethod
    def _is_within(path: Path, root: Path) -> bool:
        try:
            path.resolve(strict=False).relative_to(root.resolve(strict=False))
            return True
        except ValueError:
            return False
