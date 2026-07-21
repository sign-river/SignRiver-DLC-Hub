from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from signriver_launcher.config import UpdateSettings
from signriver_launcher.errors import DownloadError, IntegrityError, PackageError
from signriver_launcher.models import ReleaseInfo
from signriver_launcher.paths import RuntimePaths
from signriver_launcher.state import StateStore
from signriver_launcher.updater import UpdateClient


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def create_module_package(path: Path, version: str = "0.1.1") -> None:
    metadata = {
        "version": version,
        "api_version": 1,
        "entrypoint": "app_entry.py:create_application",
    }
    with zipfile.ZipFile(path, "w") as package:
        package.writestr("module.json", json.dumps(metadata))
        package.writestr(
            "app_entry.py",
            "class App:\n"
            "    def run(self): pass\n"
            "def create_application(context): return App()\n",
        )


def release_for(path: Path, version: str = "0.1.1") -> ReleaseInfo:
    return ReleaseInfo(
        version=version,
        kind="module",
        package_url="https://example.test/module.zip",
        sha256=digest(path),
        size=path.stat().st_size,
        min_launcher_version="0.1.0",
    )


def client_for(tmp_path: Path) -> tuple[UpdateClient, StateStore, RuntimePaths]:
    paths = RuntimePaths(tmp_path)
    paths.ensure()
    initial = paths.versions_dir / "0.1.0"
    initial.mkdir()
    (initial / "module.json").write_text("{}", encoding="utf-8")
    store = StateStore(paths.state_file)
    store.bootstrap("0.1.0")
    return UpdateClient(paths, UpdateSettings(), store), store, paths


def test_installs_to_new_version_and_atomically_activates(tmp_path) -> None:
    client, store, paths = client_for(tmp_path)
    archive = tmp_path / "module.zip"
    create_module_package(archive)

    client.install_archive(archive, release_for(archive))

    state = store.load()
    assert state.active_version == "0.1.1"
    assert state.previous_version == "0.1.0"
    assert state.pending_version == "0.1.1"
    assert (paths.versions_dir / "0.1.1" / "app_entry.py").is_file()


def test_rejects_hash_mismatch(tmp_path) -> None:
    client, store, paths = client_for(tmp_path)
    archive = tmp_path / "module.zip"
    create_module_package(archive)
    release = release_for(archive)
    archive.write_bytes(archive.read_bytes() + b"tampered")

    with pytest.raises(IntegrityError):
        client.install_archive(archive, release)
    assert store.load().active_version == "0.1.0"
    assert not (paths.versions_dir / "0.1.1").exists()


def test_rejects_zip_path_traversal(tmp_path) -> None:
    client, store, paths = client_for(tmp_path)
    archive = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive, "w") as package:
        package.writestr("../escaped.txt", "no")
        package.writestr(
            "module.json",
            json.dumps(
                {
                    "version": "0.1.1",
                    "api_version": 1,
                    "entrypoint": "app_entry.py:create_application",
                }
            ),
        )
        package.writestr("app_entry.py", "def create_application(context): pass")

    with pytest.raises(PackageError):
        client.install_archive(archive, release_for(archive))
    assert not (tmp_path / "escaped.txt").exists()
    assert store.load().active_version == "0.1.0"


def test_replaces_invalid_non_active_version_directory(tmp_path: Path) -> None:
    client, store, paths = client_for(tmp_path)
    archive = tmp_path / "module.zip"
    create_module_package(archive)
    invalid = paths.versions_dir / "0.1.1"
    invalid.mkdir()
    (invalid / "partial.txt").write_text("interrupted", encoding="utf-8")

    client.install_archive(archive, release_for(archive))

    assert store.load().active_version == "0.1.1"
    assert (invalid / "app_entry.py").is_file()
    assert not (invalid / "partial.txt").exists()
    assert not tuple(paths.staging_dir.iterdir())


def test_never_replaces_damaged_active_version_directory(tmp_path: Path) -> None:
    client, store, paths = client_for(tmp_path)
    archive = tmp_path / "module.zip"
    create_module_package(archive, version="0.1.0")
    active = paths.versions_dir / "0.1.0"
    marker = active / "keep.txt"
    marker.write_text("untouched", encoding="utf-8")

    with pytest.raises(PackageError, match="应用模块已损坏"):
        client.install_archive(archive, release_for(archive, version="0.1.0"))

    assert store.load().active_version == "0.1.0"
    assert marker.read_text(encoding="utf-8") == "untouched"


def test_restores_displaced_directory_when_activation_fails(tmp_path: Path) -> None:
    client, store, paths = client_for(tmp_path)
    archive = tmp_path / "module.zip"
    create_module_package(archive)
    invalid = paths.versions_dir / "0.1.1"
    invalid.mkdir()
    marker = invalid / "partial.txt"
    marker.write_text("preserve me", encoding="utf-8")

    class FailingStore:
        load = staticmethod(store.load)

        @staticmethod
        def activate(_version: str):
            raise OSError("state disk unavailable")

    client.state_store = FailingStore()

    with pytest.raises(PackageError, match="state disk unavailable"):
        client.install_archive(archive, release_for(archive))

    assert marker.read_text(encoding="utf-8") == "preserve me"
    assert not (invalid / "app_entry.py").exists()
    assert store.load().active_version == "0.1.0"


@pytest.mark.parametrize(
    "url",
    [
        "https://user@example.test/module.zip",
        "https://user:secret@example.test/module.zip",
        "http://user@example.test/module.zip",
    ],
)
def test_rejects_update_urls_with_embedded_credentials(
    tmp_path: Path, url: str
) -> None:
    client, _store, _paths = client_for(tmp_path)

    with pytest.raises(DownloadError, match="without embedded credentials"):
        client._validate_remote_url(url)
