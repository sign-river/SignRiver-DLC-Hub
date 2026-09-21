"""Local artifact discovery and immutable fingerprint helpers."""

from __future__ import annotations

import hashlib
import re
from dataclasses import asdict
from pathlib import Path

from .release_models import ReleaseArtifact
from .updates import inspect_module_archive

_PROGRAM_PACKAGE = re.compile(
    r"^SignRiver-DLC-Hub-full-v(?P<version>[^-]+)-(?P<platform>windows|steamos|macos)-(?P<arch>x64)\.zip$"
)
_MODULE_ARCHIVE = re.compile(r"^SignRiver-DLC-Hub-module-v(?P<version>[^.]+(?:\.[^.]+)*)\.zip$")
_ROLE_BY_PLATFORM = {
    "windows": "windows_full",
    "steamos": "steamos_full",
    "macos": "macos_full",
}


def file_sha256(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def fingerprint_artifact(path: Path, *, role: str, platform: str | None = None,
                         architecture: str | None = None, version: str | None = None,
                         required: bool = True) -> ReleaseArtifact:
    resolved = path.resolve(strict=True)
    stat = resolved.stat()
    return ReleaseArtifact(
        role=role,
        filename=resolved.name,
        platform=platform,
        architecture=architecture,
        version=version,
        local_path=str(resolved),
        size=stat.st_size,
        modified_ns=stat.st_mtime_ns,
        sha256=file_sha256(resolved),
        required=required,
    )


class ArtifactCollector:
    """Discovers candidates without mutating files or contacting remote services."""

    def collect_program_packages(self, directory: Path | str, *, version: str) -> list[ReleaseArtifact]:
        root = Path(directory)
        artifacts: list[ReleaseArtifact] = []
        if not root.is_dir():
            return artifacts
        for path in sorted(root.iterdir()):
            if not path.is_file():
                continue
            match = _PROGRAM_PACKAGE.fullmatch(path.name)
            if not match or match.group("version") != version:
                continue
            platform = match.group("platform")
            artifacts.append(
                fingerprint_artifact(
                    path,
                    role=_ROLE_BY_PLATFORM[platform],
                    platform=platform,
                    architecture=match.group("arch"),
                    version=version,
                )
            )
        return artifacts

    def collect_program_module_artifacts(
        self, directory: Path | str, *, version: str
    ) -> list[ReleaseArtifact]:
        """Collect every valid module archive kept in the module inbox.

        The collector checks both the conventional ``modules`` child directory
        and the inbox root, while de-duplicating by resolved path.

        模块归档目录是 ``modules`` Release 的唯一数据源：目录里放什么就同步
        什么，所以历史版本也一并收集（它们会被重新上传，保证云端始终等于仓库
        基线——CI 会按 ``config/module-archives.json`` 逐个校验这些哈希）。
        只有与本次发布版本一致的那份是 ``required``，缺失即预检失败。
        """
        root = Path(directory)
        if not root.is_dir():
            return []
        candidates = list(root.glob("SignRiver-DLC-Hub-module-v*.zip"))
        module_dir = root / "modules"
        if module_dir.is_dir():
            candidates.extend(module_dir.glob("SignRiver-DLC-Hub-module-v*.zip"))
        artifacts: list[ReleaseArtifact] = []
        seen: set[Path] = set()
        for path in sorted(candidates):
            resolved = path.resolve()
            if resolved in seen or not path.is_file():
                continue
            seen.add(resolved)
            try:
                info = inspect_module_archive(path)
            except (OSError, ValueError):
                continue
            artifacts.append(
                fingerprint_artifact(
                    path,
                    role="module_archive",
                    version=info.version,
                    required=info.version == version,
                )
            )
        return artifacts

    @staticmethod
    def has_fingerprint_changed(artifact: ReleaseArtifact) -> bool:
        if not artifact.local_path or artifact.size is None or artifact.modified_ns is None or not artifact.sha256:
            return True
        path = Path(artifact.local_path)
        if not path.is_file():
            return True
        stat = path.stat()
        if stat.st_size != artifact.size or stat.st_mtime_ns != artifact.modified_ns:
            return True
        return file_sha256(path) != artifact.sha256

    @staticmethod
    def snapshot(artifacts: list[ReleaseArtifact]) -> list[dict[str, object]]:
        return [asdict(artifact) for artifact in artifacts]
