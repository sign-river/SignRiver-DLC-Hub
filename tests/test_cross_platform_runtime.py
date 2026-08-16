from __future__ import annotations

import json
import hashlib
import zipfile
from pathlib import Path

import pytest

from signriver_common.platforms import (
    HostPlatform,
    detect_host_platform,
    normalize_architecture,
    platform_package_key,
)
from signriver_launcher.errors import FullUpdateError
from signriver_launcher.full_update import FullUpdateManager
from signriver_launcher.errors import ManifestError
from signriver_launcher.models import FullReleaseManifest, ReleaseInfo
from signriver_launcher.paths import RuntimePaths
from signriver_launcher.config import UpdateSettings
from signriver_launcher.state import StateStore
from signriver_launcher.updater import UpdateClient


def test_platform_and_architecture_normalization() -> None:
    assert detect_host_platform("win32") is HostPlatform.WINDOWS
    assert detect_host_platform("linux") is HostPlatform.STEAMOS
    assert detect_host_platform("darwin") is HostPlatform.MACOS
    assert normalize_architecture("AMD64") == "x64"
    assert platform_package_key("macos", "x86_64") == "macos-x64"


def test_release_selects_only_an_exact_platform_package() -> None:
    digest = "a" * 64
    release = ReleaseInfo.from_dict({
        "version": "0.2.0", "kind": "full", "package_url": "windows.zip",
        "sha256": digest, "min_launcher_version": "0.1.2",
        "platform_packages": {
            "windows-x64": {"package_url": "windows.zip", "sha256": digest, "size": 1},
            "steamos-x64": {"package_url": "linux.zip", "sha256": "b" * 64, "size": 2},
        },
    })
    selected = release.for_platform("steamos-x64")
    assert selected is not None and selected.package_url == "linux.zip"
    assert release.for_platform("macos-x64") is None


def test_legacy_top_level_full_package_is_windows_only() -> None:
    release = ReleaseInfo.from_dict({
        "version": "0.2.0", "kind": "full", "package_url": "windows.zip",
        "sha256": "a" * 64, "min_launcher_version": "0.1.2",
    })
    assert release.for_platform("windows-x64") is release
    assert release.for_platform("steamos-x64") is None
    assert release.for_platform("macos-x64") is None

    module = ReleaseInfo.from_dict({
        "version": "0.2.1", "kind": "module", "package_url": "module.zip",
        "sha256": "b" * 64, "min_launcher_version": "0.2.0",
    })
    assert module.for_platform("steamos-x64") is module


def test_full_manifest_accepts_mode_and_rejects_wrong_platform(tmp_path: Path) -> None:
    payload = b"binary"
    digest = __import__("hashlib").sha256(payload).hexdigest()
    manifest = {
        "schema_version": 1,
        "version": "0.2.0",
        "target_platform": "steamos",
        "target_arch": "x64",
        "files": [{"path": "SignRiver-DLC-Hub", "size": len(payload), "sha256": digest, "mode": 0o755}],
    }
    parsed = FullReleaseManifest.from_dict(manifest)
    assert parsed.files[0].mode == 0o755
    archive = tmp_path / "update.zip"
    with zipfile.ZipFile(archive, "w") as package:
        package.writestr("release-manifest.json", json.dumps(manifest))
        package.writestr("SignRiver-DLC-Hub", payload)
    paths = RuntimePaths(
        tmp_path / "state", tmp_path / "install", HostPlatform.MACOS,
        tmp_path / "cache",
    )
    paths.ensure()
    release = ReleaseInfo("0.2.0", "full", "unused", digest, None, "0.1.2")
    with pytest.raises(FullUpdateError, match="different platform"):
        FullUpdateManager(paths).prepare(archive, release)


def test_macos_packaged_runtime_maps_to_writable_state(tmp_path: Path) -> None:
    bundle = tmp_path / "SignRiver-DLC-Hub.app"
    runtime = bundle / "Contents" / "Resources" / "runtime"
    (runtime / "app" / "versions" / "0.2.0").mkdir(parents=True)
    (runtime / "app" / "versions" / "0.2.0" / "module.json").write_text(
        '{"version":"0.2.0"}', encoding="utf-8"
    )
    (runtime / "app" / "state.json").write_text("{}", encoding="utf-8")
    paths = RuntimePaths(
        tmp_path / "state", bundle, HostPlatform.MACOS, tmp_path / "cache"
    )
    paths.ensure()
    assert (
        tmp_path / "state" / "app" / "versions" / "0.2.0" / "module.json"
    ).is_file()
    assert paths.managed_target(
        "Contents/Resources/runtime/app/versions/0.2.0/module.json"
    ) == tmp_path / "state" / "app" / "versions" / "0.2.0" / "module.json"


def test_steamos_packaged_runtime_seeds_missing_modules(tmp_path: Path) -> None:
    install = tmp_path / "install"
    module = install / "app" / "versions" / "0.2.0"
    module.mkdir(parents=True)
    (module / "module.json").write_text('{"version":"0.2.0"}', encoding="utf-8")
    (install / "app" / "state.json").write_text(
        '{"active_version":"0.2.0"}', encoding="utf-8"
    )
    paths = RuntimePaths(
        tmp_path / "state", install, HostPlatform.STEAMOS, tmp_path / "cache"
    )

    paths.ensure()

    assert (paths.versions_dir / "0.2.0" / "module.json").is_file()


def test_update_client_reports_missing_platform_package(tmp_path: Path, monkeypatch) -> None:
    paths = RuntimePaths(tmp_path)
    paths.ensure()
    store = StateStore(paths.state_file)
    store.bootstrap("0.1.7")
    settings = UpdateSettings(manifest_url="https://example.test/update.json")
    client = UpdateClient(paths, settings, store, host_package_key="macos-x64")
    release = ReleaseInfo.from_dict({
        "version": "0.2.0", "kind": "full", "package_url": "windows.zip",
        "sha256": "a" * 64,
        "platform_packages": {
            "windows-x64": {"package_url": "windows.zip", "sha256": "a" * 64}
        },
    })
    from signriver_launcher.models import UpdateManifest

    monkeypatch.setattr(client, "_fetch_manifest", lambda: UpdateManifest("stable", (release,)))
    with pytest.raises(ManifestError, match="当前平台暂无此更新"):
        client.check("0.1.7")


def test_macos_full_update_atomically_swaps_and_restores_app_bundle(
    tmp_path: Path,
) -> None:
    bundle = tmp_path / "SignRiver-DLC-Hub.app"
    old_binary = bundle / "Contents" / "MacOS" / "SignRiver-DLC-Hub"
    old_binary.parent.mkdir(parents=True)
    old_binary.write_bytes(b"old")
    paths = RuntimePaths(
        tmp_path / "state", bundle, HostPlatform.MACOS, tmp_path / "cache"
    )
    paths.ensure()
    store = StateStore(paths.state_file)
    store.bootstrap("0.1.7")
    prefix = "SignRiver-DLC-Hub.app/"
    files = {
        f"{prefix}Contents/MacOS/SignRiver-DLC-Hub": b"new",
        f"{prefix}Contents/Resources/runtime/app/versions/0.2.0/module.json": json.dumps(
            {
                "version": "0.2.0",
                "api_version": 3,
                "entrypoint": "app_entry.py:create_application",
            }
        ).encode(),
        f"{prefix}Contents/Resources/runtime/app/versions/0.2.0/app_entry.py": b"new",
    }
    manifest = {
        "schema_version": 1,
        "version": "0.2.0",
        "target_platform": "macos",
        "target_arch": "x64",
        "bundle_path": "SignRiver-DLC-Hub.app",
        "files": [
            {
                "path": name,
                "size": len(value),
                "sha256": hashlib.sha256(value).hexdigest(),
                "mode": 0o755 if "/MacOS/" in name else 0o644,
            }
            for name, value in files.items()
        ],
    }
    archive = tmp_path / "macos-update.zip"
    with zipfile.ZipFile(archive, "w") as package:
        package.writestr("release-manifest.json", json.dumps(manifest))
        for name, value in files.items():
            package.writestr(name, value)
    release = ReleaseInfo(
        "0.2.0", "full", "unused", hashlib.sha256(archive.read_bytes()).hexdigest(),
        archive.stat().st_size, "0.1.2",
    )
    manager = FullUpdateManager(paths)

    transaction = manager.prepare(archive, release)
    manager.apply(transaction.transaction_id)

    assert old_binary.read_bytes() == b"new"
    assert Path(manager.load().backup_path).is_dir()  # type: ignore[union-attr]
    manager.rollback(transaction.transaction_id)
    assert old_binary.read_bytes() == b"old"
    assert store.load().active_version == "0.1.7"
