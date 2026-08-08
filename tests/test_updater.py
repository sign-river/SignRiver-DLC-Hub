from __future__ import annotations

import hashlib
import json
import subprocess
import urllib.error
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from signriver_launcher.config import UpdateSettings
from signriver_launcher.errors import (
    DownloadCancelled,
    DownloadError,
    IntegrityError,
    PackageError,
)
from signriver_launcher.models import ReleaseInfo
from signriver_launcher.paths import RuntimePaths
from signriver_launcher.product import RELEASE_EXE_NAME
from signriver_launcher.state import StateStore
from signriver_launcher.updater import UpdateClient
import signriver_launcher.updater as updater_module


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


def test_update_download_can_be_cancelled_and_cleans_partial_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _store, paths = client_for(tmp_path)
    payload = b"first" + b"second"
    release = ReleaseInfo(
        "0.1.1", "module", "https://example.test/module.zip",
        hashlib.sha256(payload).hexdigest(), len(payload), "0.1.0",
    )

    class Response:
        def __init__(self) -> None:
            self._chunks = iter((b"first", b"second"))
            self.headers = {"Content-Length": str(len(payload))}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def geturl(self):
            return release.package_url

        def read(self, _size):
            return next(self._chunks, b"")

    monkeypatch.setattr(
        updater_module.urllib.request, "urlopen", lambda *_args, **_kwargs: Response()
    )
    cancelled = False

    def progress(_current: int, _total: int | None) -> None:
        nonlocal cancelled
        cancelled = True

    with pytest.raises(DownloadCancelled, match="已取消"):
        client.download(release, progress, lambda: cancelled)

    assert not tuple(paths.cache_dir.glob("module-0.1.1-*.zip*"))


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


def test_selected_download_source_controls_manifest_and_relative_package_url(
    tmp_path: Path, monkeypatch
) -> None:
    client, _store, _paths = client_for(tmp_path)
    client.settings = UpdateSettings(
        manifest_urls={
            "gitlink": "https://gitlink.example/updates/update-manifest.json",
            "github": "https://github.example/updates/update-manifest.json",
        }
    )
    client.set_download_source("github")
    requested = []
    payload = json.dumps(
        {
            "schema_version": 1,
            "channel": "stable",
            "releases": [
                {
                    "version": "0.1.1",
                    "kind": "module",
                    "package_url": "module-v0.1.1.zip",
                    "sha256": "a" * 64,
                    "size": 1,
                    "min_launcher_version": "0.1.0",
                }
            ],
        }
    ).encode()

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def geturl(self):
            return requested[-1].full_url

        def read(self, _size):
            return payload

    def open_request(request, timeout):
        requested.append(request)
        assert timeout == 20
        return Response()

    monkeypatch.setattr(updater_module.urllib.request, "urlopen", open_request)

    manifest = client._fetch_manifest()

    assert requested[0].full_url == (
        "https://github.example/updates/update-manifest.json"
    )
    assert manifest.releases[0].package_url == (
        "https://github.example/updates/module-v0.1.1.zip"
    )


def test_frozen_full_update_uses_staged_new_launcher_as_helper(
    tmp_path: Path, monkeypatch
) -> None:
    client, _store, paths = client_for(tmp_path)
    staging = tmp_path / "staging"
    staging.mkdir()
    staged_launcher = staging / RELEASE_EXE_NAME
    staged_launcher.write_bytes(b"new launcher")
    transaction = SimpleNamespace(
        staging_path=str(staging),
        transaction_id="transaction-id",
    )
    release = ReleaseInfo(
        "0.1.2",
        "full",
        "https://example.test/full.zip",
        "a" * 64,
        1,
        "0.1.0",
    )
    calls = []
    monkeypatch.setattr(
        client, "prepare_full_update", lambda *_args, **_kwargs: transaction
    )
    monkeypatch.setattr(updater_module.sys, "frozen", True, raising=False)
    monkeypatch.setattr(
        updater_module.subprocess,
        "Popen",
        lambda command, **kwargs: calls.append((command, kwargs)),
    )

    client.start_full_update(release)

    helper = staging / "full-update-helper.exe"
    assert helper.read_bytes() == b"new launcher"
    assert calls[0][0][0] == str(helper)
    assert calls[0][1]["cwd"] == paths.root
    assert calls[0][1]["stdin"] == subprocess.DEVNULL



def _manifest_payload() -> bytes:
    return json.dumps(
        {
            "schema_version": 1,
            "channel": "stable",
            "releases": [
                {
                    "version": "0.1.1",
                    "kind": "module",
                    "package_url": "module-v0.1.1.zip",
                    "sha256": "a" * 64,
                    "size": 1,
                    "min_launcher_version": "0.1.0",
                }
            ],
        }
    ).encode()


def test_fetch_manifest_retries_transient_network_errors(tmp_path, monkeypatch) -> None:
    client, _store, _paths = client_for(tmp_path)
    client.settings = UpdateSettings(
        manifest_urls={
            "gitlink": "https://gitlink.example/updates/update-manifest.json",
            "github": "https://github.example/updates/update-manifest.json",
        }
    )
    client.set_download_source("github")
    attempts: list[str] = []
    payload = _manifest_payload()

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def geturl(self):
            return "https://example.test/update-manifest.json"

        def read(self, _size):
            return payload

    def open_request(request, timeout):
        attempts.append(request.full_url)
        if len(attempts) < 3:
            raise urllib.error.URLError("connection reset")
        return Response()

    monkeypatch.setattr(updater_module.urllib.request, "urlopen", open_request)
    monkeypatch.setattr(updater_module.time, "sleep", lambda _seconds: None)

    manifest = client._fetch_manifest()

    assert len(attempts) == 3
    assert manifest.releases[0].version == "0.1.1"


def test_fetch_manifest_raises_after_all_retries_exhausted(tmp_path, monkeypatch) -> None:
    client, _store, _paths = client_for(tmp_path)
    client.settings = UpdateSettings(
        manifest_urls={
            "gitlink": "https://gitlink.example/updates/update-manifest.json",
            "github": "https://github.example/updates/update-manifest.json",
        }
    )
    client.set_download_source("github")
    attempts: list[str] = []

    def open_request(request, timeout):
        attempts.append(request.full_url)
        raise urllib.error.URLError("connection reset")

    monkeypatch.setattr(updater_module.urllib.request, "urlopen", open_request)
    monkeypatch.setattr(updater_module.time, "sleep", lambda _seconds: None)

    with pytest.raises(DownloadError):
        client._fetch_manifest()

    assert len(attempts) == 3



def _manifest_with_release(version: str, kind: str) -> bytes:
    return json.dumps(
        {
            "schema_version": 1,
            "channel": "stable",
            "releases": [
                {
                    "version": version,
                    "kind": kind,
                    "package_url": f"{kind}-v{version}.zip",
                    "sha256": "a" * 64,
                    "size": 1,
                    "min_launcher_version": "0.1.0",
                }
            ],
        }
    ).encode()


def _manifest_response(payload: bytes):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def geturl(self):
            return "https://example.test/update-manifest.json"

        def read(self, _size):
            return payload

    return Response()


def test_bad_full_release_is_still_offered_for_reinstall(tmp_path, monkeypatch) -> None:
    client, store, _paths = client_for(tmp_path)
    client.settings = UpdateSettings(
        manifest_urls={
            "gitlink": "https://gitlink.example/updates/update-manifest.json",
            "github": "https://github.example/updates/update-manifest.json",
        }
    )
    client.set_download_source("github")
    state = store.load()
    state.bad_versions = ["0.1.1"]
    store.save(state)
    payload = _manifest_with_release("0.1.1", "full")
    monkeypatch.setattr(
        updater_module.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: _manifest_response(payload),
    )

    release = client.check("0.1.0")

    assert release is not None
    assert release.version == "0.1.1"
    assert release.kind == "full"


def test_bad_module_release_is_excluded_from_updates(tmp_path, monkeypatch) -> None:
    client, store, _paths = client_for(tmp_path)
    client.settings = UpdateSettings(
        manifest_urls={
            "gitlink": "https://gitlink.example/updates/update-manifest.json",
            "github": "https://github.example/updates/update-manifest.json",
        }
    )
    client.set_download_source("github")
    state = store.load()
    state.bad_versions = ["0.1.1"]
    store.save(state)
    payload = _manifest_with_release("0.1.1", "module")
    monkeypatch.setattr(
        updater_module.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: _manifest_response(payload),
    )

    release = client.check("0.1.0")

    assert release is None
