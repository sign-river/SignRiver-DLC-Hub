from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile
from collections.abc import Callable
from pathlib import Path, PurePosixPath

from .config import UpdateSettings
from .constants import (
    LAUNCHER_VERSION,
    MAX_ARCHIVE_FILES,
    MAX_ARCHIVE_UNCOMPRESSED_BYTES,
    MAX_MANIFEST_BYTES,
)
from .errors import DownloadError, FullUpdateRequired, IntegrityError, ManifestError, PackageError
from .jsonio import read_json
from .models import ModuleMetadata, ReleaseInfo, UpdateManifest
from .paths import RuntimePaths
from .state import StateStore
from .versioning import Version

ProgressCallback = Callable[[int, int | None], None]


class UpdateClient:
    """Downloads and atomically activates external application modules."""

    def __init__(
        self,
        paths: RuntimePaths,
        settings: UpdateSettings,
        state_store: StateStore,
        launcher_version: str = LAUNCHER_VERSION,
    ) -> None:
        self.paths = paths
        self.settings = settings
        self.state_store = state_store
        self.launcher_version = launcher_version

    @property
    def enabled(self) -> bool:
        return bool(self.settings.manifest_url)

    def check(self, current_version: str) -> ReleaseInfo | None:
        if not self.enabled:
            return None
        manifest = self._fetch_manifest()
        if manifest.channel != self.settings.channel:
            raise ManifestError(
                f"Configured channel {self.settings.channel!r} received {manifest.channel!r}"
            )
        current = Version.parse(current_version)
        launcher = Version.parse(self.launcher_version)
        bad_versions = set(self.state_store.load().bad_versions)
        candidates = [
            release
            for release in manifest.releases
            if Version.parse(release.version) > current
            and release.version not in bad_versions
        ]
        if not candidates:
            return None
        compatible_modules = [
            release
            for release in candidates
            if release.kind == "module" and Version.parse(release.min_launcher_version) <= launcher
        ]
        full_updates = [release for release in candidates if release.kind == "full"]
        incompatible_modules = [
            release
            for release in candidates
            if release.kind == "module" and Version.parse(release.min_launcher_version) > launcher
        ]
        # A full update takes priority when the newest module cannot run on this launcher.
        if incompatible_modules and full_updates:
            newest_incompatible = max(incompatible_modules, key=lambda item: Version.parse(item.version))
            newest_full = max(full_updates, key=lambda item: Version.parse(item.version))
            if Version.parse(newest_full.version) >= Version.parse(newest_incompatible.version):
                return newest_full
        available = [*compatible_modules, *full_updates]
        return max(available, key=lambda item: Version.parse(item.version)) if available else None

    def install(
        self,
        release: ReleaseInfo,
        progress: ProgressCallback | None = None,
    ) -> str:
        if release.kind == "full":
            raise FullUpdateRequired(release.version, release.package_url, release.notes)
        archive = self.download(release, progress)
        try:
            self.install_archive(archive, release)
        finally:
            archive.unlink(missing_ok=True)
        return release.version

    def download(self, release: ReleaseInfo, progress: ProgressCallback | None = None) -> Path:
        url = self._resolve_url(release.package_url)
        self._validate_remote_url(url)
        self.paths.cache_dir.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(
            prefix=f"module-{release.version}-", suffix=".zip.part", dir=self.paths.cache_dir
        )
        os.close(fd)
        target = Path(temp_name)
        request = urllib.request.Request(
            url,
            headers={"User-Agent": f"SignRiver-DLC-Hub/{self.launcher_version}"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.settings.timeout_seconds) as response, target.open(
                "wb"
            ) as output:
                self._validate_remote_url(response.geturl())
                response_size = response.headers.get("Content-Length")
                total = int(response_size) if response_size and response_size.isdigit() else release.size
                if release.size is not None and total is not None and total != release.size:
                    raise IntegrityError("The server-reported package size does not match the manifest")
                digest = hashlib.sha256()
                downloaded = 0
                while True:
                    chunk = response.read(1024 * 256)
                    if not chunk:
                        break
                    output.write(chunk)
                    digest.update(chunk)
                    downloaded += len(chunk)
                    if progress:
                        progress(downloaded, total)
                output.flush()
                os.fsync(output.fileno())
            if release.size is not None and downloaded != release.size:
                raise IntegrityError(
                    f"Package size mismatch: expected {release.size}, downloaded {downloaded}"
                )
            if digest.hexdigest() != release.sha256:
                raise IntegrityError("Package SHA-256 does not match the update manifest")
            final_path = target.with_suffix("")
            os.replace(target, final_path)
            return final_path
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise DownloadError(f"Unable to download update: {error}") from error
        finally:
            target.unlink(missing_ok=True)

    def install_archive(self, archive: Path, release: ReleaseInfo) -> None:
        actual_digest = self._sha256(archive)
        if actual_digest != release.sha256:
            raise IntegrityError("Local package SHA-256 does not match the update manifest")
        if release.size is not None and archive.stat().st_size != release.size:
            raise IntegrityError("Local package size does not match the update manifest")

        self.paths.staging_dir.mkdir(parents=True, exist_ok=True)
        stage = self.paths.staging_dir / f"{release.version}-{uuid.uuid4().hex}"
        destination = self.paths.versions_dir / release.version
        replace_invalid_destination = False
        if destination.exists():
            try:
                metadata = self._validate_module(destination, release.version)
            except PackageError:
                state = self.state_store.load()
                if state.active_version == release.version:
                    raise PackageError(
                        "The active application module is damaged; refusing to "
                        "replace files while that version is running"
                    )
                replace_invalid_destination = True
            else:
                if metadata.version == release.version:
                    self.state_store.activate(release.version)
                    return
        displaced = self.paths.staging_dir / (
            f"{release.version}-invalid-{uuid.uuid4().hex}"
        )
        installed = False
        activated = False
        try:
            stage.mkdir(parents=True)
            self._safe_extract(archive, stage)
            self._validate_module(stage, release.version)
            self.paths.versions_dir.mkdir(parents=True, exist_ok=True)
            if replace_invalid_destination:
                os.replace(destination, displaced)
            try:
                os.replace(stage, destination)
                installed = True
                self.state_store.activate(release.version)
                activated = True
            except BaseException:
                # If activation itself fails, restore the previous directory
                # rather than leaving state.json and versions/ inconsistent.
                if installed and destination.exists():
                    shutil.rmtree(destination, ignore_errors=True)
                if displaced.exists() and not destination.exists():
                    os.replace(displaced, destination)
                raise
        except (zipfile.BadZipFile, OSError, RuntimeError, ValueError) as error:
            raise PackageError(f"Unable to install module package: {error}") from error
        finally:
            if stage.exists():
                shutil.rmtree(stage, ignore_errors=True)
            if displaced.exists() and activated:
                shutil.rmtree(displaced, ignore_errors=True)

    def _fetch_manifest(self) -> UpdateManifest:
        url = self.settings.manifest_url
        self._validate_remote_url(url)
        request = urllib.request.Request(
            url,
            headers={"User-Agent": f"SignRiver-DLC-Hub/{self.launcher_version}"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.settings.timeout_seconds) as response:
                self._validate_remote_url(response.geturl())
                raw = response.read(MAX_MANIFEST_BYTES + 1)
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise DownloadError(f"Unable to fetch update manifest: {error}") from error
        if len(raw) > MAX_MANIFEST_BYTES:
            raise ManifestError("Update manifest is too large")
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ManifestError(f"Update manifest is not valid UTF-8 JSON: {error}") from error
        if not isinstance(value, dict):
            raise ManifestError("Update manifest root must be an object")
        return UpdateManifest.from_dict(value)

    def _safe_extract(self, archive: Path, destination: Path) -> None:
        with zipfile.ZipFile(archive) as package:
            entries = package.infolist()
            if len(entries) > MAX_ARCHIVE_FILES:
                raise PackageError("Module package contains too many files")
            total_size = sum(entry.file_size for entry in entries)
            if total_size > MAX_ARCHIVE_UNCOMPRESSED_BYTES:
                raise PackageError("Module package expands beyond the safety limit")
            for entry in entries:
                normalized_name = entry.filename.replace("\\", "/")
                member = PurePosixPath(normalized_name)
                if member.is_absolute() or ".." in member.parts or not member.parts:
                    raise PackageError(f"Unsafe archive path: {entry.filename}")
                mode = entry.external_attr >> 16
                if stat.S_ISLNK(mode):
                    raise PackageError(f"Symbolic links are not allowed: {entry.filename}")
                target = destination.joinpath(*member.parts)
                resolved_target = target.resolve()
                if destination.resolve() not in resolved_target.parents and resolved_target != destination.resolve():
                    raise PackageError(f"Archive entry escapes staging directory: {entry.filename}")
                if entry.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with package.open(entry) as source, target.open("wb") as output:
                    shutil.copyfileobj(source, output, length=1024 * 256)

    @staticmethod
    def _validate_module(directory: Path, expected_version: str) -> ModuleMetadata:
        try:
            metadata = ModuleMetadata.from_dict(read_json(directory / "module.json"))
        except (FileNotFoundError, OSError, ValueError) as error:
            raise PackageError(f"Invalid module metadata: {error}") from error
        if metadata.version != expected_version:
            raise PackageError(
                f"Module version {metadata.version} does not match release {expected_version}"
            )
        entry_path, _ = metadata.entrypoint.rsplit(":", 1)
        candidate = (directory / entry_path).resolve()
        if directory.resolve() not in candidate.parents or not candidate.is_file():
            raise PackageError(f"Module entrypoint does not exist: {entry_path}")
        return metadata

    def _resolve_url(self, package_url: str) -> str:
        return urllib.parse.urljoin(self.settings.manifest_url, package_url)

    def _validate_remote_url(self, url: str) -> None:
        parsed = urllib.parse.urlparse(url)
        has_safe_authority = bool(
            parsed.hostname and parsed.username is None and parsed.password is None
        )
        if parsed.scheme == "https" and has_safe_authority:
            return
        if (
            parsed.scheme == "http"
            and has_safe_authority
            and self.settings.allow_insecure_http
        ):
            return
        raise DownloadError("Update URLs must use HTTPS without embedded credentials")

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as file:
            for chunk in iter(lambda: file.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
