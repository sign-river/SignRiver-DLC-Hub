from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from signriver_launcher.errors import FullUpdateError
from signriver_launcher.full_update import FullUpdateManager
from signriver_launcher.full_update_helper import (
    _wait_for_parent,
    cleanup_full_update_helper,
    frozen_child_environment,
    rollback_full_update,
)
from signriver_launcher.main import (
    _activate_confirmed_full_update_module,
    _defer_windows_full_update_rollback,
)
from signriver_launcher.models import ReleaseInfo
from signriver_launcher.models import FullReleaseManifest, ReleaseFile
from signriver_launcher.paths import RuntimePaths
from signriver_launcher.state import StateStore
from signriver_common.platforms import HostPlatform


def _digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _archive(
    path: Path, version: str = "0.2.0", files: dict[str, bytes] | None = None
) -> ReleaseInfo:
    files = files or {"launcher.exe": b"new launcher", "app/new.txt": b"new app"}
    manifest = {
        "schema_version": 1,
        "version": version,
        "files": [
            {"path": name, "size": len(value), "sha256": _digest(value)}
            for name, value in files.items()
        ],
    }
    with zipfile.ZipFile(path, "w") as package:
        package.writestr("release-manifest.json", json.dumps(manifest))
        for name, value in files.items():
            package.writestr(name, value)
    data = path.read_bytes()
    return ReleaseInfo(
        version,
        "full",
        "https://example.test/full.zip",
        _digest(data),
        len(data),
        "0.1.0",
    )


def test_full_update_swaps_only_manifest_owned_files_and_preserves_user_state(
    tmp_path: Path,
) -> None:
    paths = RuntimePaths(tmp_path)
    paths.ensure()
    (tmp_path / "launcher.exe").write_bytes(b"old launcher")
    (tmp_path / "app").mkdir(exist_ok=True)
    (tmp_path / "app" / "old.txt").write_bytes(b"old app")
    (paths.data_dir / "settings.json").write_text('{"keep": true}', encoding="utf-8")
    (paths.cache_dir / "dlc.zip").write_bytes(b"cached")
    package = tmp_path / "full.zip"
    release = _archive(package)

    manager = FullUpdateManager(paths)
    transaction = manager.prepare(package, release)
    manager.apply(transaction.transaction_id)

    assert (tmp_path / "launcher.exe").read_bytes() == b"new launcher"
    assert (tmp_path / "app" / "new.txt").read_bytes() == b"new app"
    assert (tmp_path / "app" / "old.txt").read_bytes() == b"old app"
    assert (paths.data_dir / "settings.json").read_text(
        encoding="utf-8"
    ) == '{"keep": true}'
    assert (paths.cache_dir / "dlc.zip").read_bytes() == b"cached"
    assert manager.load() is not None and manager.load().stage == "swapped"


def test_full_update_rolls_back_replaced_files(tmp_path: Path) -> None:
    paths = RuntimePaths(tmp_path)
    paths.ensure()
    (tmp_path / "launcher.exe").write_bytes(b"old launcher")
    package = tmp_path / "full.zip"
    release = _archive(package)
    manager = FullUpdateManager(paths)
    transaction = manager.prepare(package, release)
    manager.apply(transaction.transaction_id)
    manager.rollback(transaction.transaction_id)

    assert (tmp_path / "launcher.exe").read_bytes() == b"old launcher"
    assert not (tmp_path / "app" / "new.txt").exists()
    assert manager.load() is not None and manager.load().stage == "rolled_back"


def test_full_update_confirmation_keeps_backup_for_later_cleanup(
    tmp_path: Path,
) -> None:
    paths = RuntimePaths(tmp_path)
    paths.ensure()
    (tmp_path / "launcher.exe").write_bytes(b"old launcher")
    package = tmp_path / "full.zip"
    release = _archive(package)
    manager = FullUpdateManager(paths)
    transaction = manager.prepare(package, release)
    manager.apply(transaction.transaction_id)
    manager.confirm(transaction.transaction_id)

    assert manager.load() is not None and manager.load().stage == "confirmed"
    assert (
        Path(transaction.backup_path) / "launcher.exe"
    ).read_bytes() == b"old launcher"
    assert not manager.lock_path.exists()


def test_full_update_refuses_a_second_pending_transaction(tmp_path: Path) -> None:
    paths = RuntimePaths(tmp_path)
    paths.ensure()
    package = tmp_path / "full.zip"
    release = _archive(package)
    manager = FullUpdateManager(paths)
    manager.prepare(package, release)

    with pytest.raises(FullUpdateError, match="already pending"):
        manager.prepare(package, release)


def test_windows_full_update_uses_compact_same_volume_paths(tmp_path: Path) -> None:
    paths = RuntimePaths(tmp_path, host_platform=HostPlatform.WINDOWS)

    assert paths.full_update_staging_dir == tmp_path / ".su"
    assert paths.full_update_backup_dir == tmp_path / ".ub"
    assert paths.full_update_staging_dir.anchor == paths.root.anchor
    assert paths.full_update_backup_dir.anchor == paths.root.anchor


def test_windows_full_update_rejects_excessive_staged_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import signriver_launcher.full_update as full_update_module

    manifest = FullReleaseManifest(
        "0.2.0",
        (ReleaseFile("a" * 250 + ".dll", 1, "a" * 64),),
    )
    monkeypatch.setattr(full_update_module.os, "name", "nt")

    with pytest.raises(FullUpdateError, match="路径过深"):
        FullUpdateManager._validate_windows_paths(
            tmp_path / ".su" / ("x" * 32),
            tmp_path / ".ub" / ("x" * 32),
            manifest,
        )


def test_full_update_recovers_when_helper_exits_before_apply(tmp_path: Path) -> None:
    paths = RuntimePaths(tmp_path)
    paths.ensure()
    package = tmp_path / "full.zip"
    release = _archive(package)
    manager = FullUpdateManager(paths)
    transaction = manager.prepare(package, release)

    recovered = manager.recover_pending()

    assert recovered is not None and recovered.stage == "rolled_back"
    assert not Path(transaction.staging_path).exists()
    assert not Path(transaction.backup_path).exists()
    assert not manager.lock_path.exists()


def test_full_update_allows_a_new_transaction_after_confirmation(
    tmp_path: Path,
) -> None:
    paths = RuntimePaths(tmp_path)
    paths.ensure()
    package = tmp_path / "full.zip"
    release = _archive(package)
    manager = FullUpdateManager(paths)
    first = manager.prepare(package, release)
    manager.apply(first.transaction_id)
    manager.confirm(first.transaction_id)

    second = manager.prepare(package, release)
    assert second.transaction_id != first.transaction_id


def test_full_update_rejects_user_data_paths_without_touching_installation(
    tmp_path: Path,
) -> None:
    paths = RuntimePaths(tmp_path)
    paths.ensure()
    package = tmp_path / "unsafe.zip"
    release = _archive(package, files={"data/evil.txt": b"no"})

    with pytest.raises(FullUpdateError, match="cannot manage"):
        FullUpdateManager(paths).prepare(package, release)
    assert not (paths.data_dir / "evil.txt").exists()


def test_full_update_rejects_manifest_hash_mismatch_before_swapping(
    tmp_path: Path,
) -> None:
    paths = RuntimePaths(tmp_path)
    paths.ensure()
    old = tmp_path / "launcher.exe"
    old.write_bytes(b"old")
    package = tmp_path / "bad.zip"
    release = _archive(package)
    with zipfile.ZipFile(package, "r") as source:
        manifest = source.read("release-manifest.json")
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr("release-manifest.json", manifest)
        archive.writestr("launcher.exe", b"tampered")
        archive.writestr("app/new.txt", b"new app")

    with pytest.raises(FullUpdateError, match="verification failed"):
        FullUpdateManager(paths).prepare(package, release)
    assert old.read_bytes() == b"old"


def test_full_update_activates_new_module_and_rolls_state_back_with_files(
    tmp_path: Path,
) -> None:
    paths = RuntimePaths(tmp_path)
    paths.ensure()
    store = StateStore(paths.state_file)
    store.bootstrap("0.1.0")
    old = paths.versions_dir / "0.1.0"
    old.mkdir()
    (old / "module.json").write_text(
        json.dumps(
            {
                "version": "0.1.0",
                "api_version": 1,
                "entrypoint": "app_entry.py:create_application",
            }
        ),
        encoding="utf-8",
    )
    (old / "app_entry.py").write_text("old", encoding="utf-8")
    metadata = json.dumps(
        {
            "version": "0.2.0",
            "api_version": 1,
            "entrypoint": "app_entry.py:create_application",
        }
    ).encode()
    files = {
        "launcher.exe": b"new launcher",
        "app/versions/0.2.0/module.json": metadata,
        "app/versions/0.2.0/app_entry.py": b"new",
    }
    package = tmp_path / "full.zip"
    release = _archive(package, files=files)
    manager = FullUpdateManager(paths)

    transaction = manager.prepare(package, release)
    assert transaction.activate_version == "0.2.0"
    manager.apply(transaction.transaction_id)

    activated = store.load()
    assert activated.active_version == "0.2.0"
    assert activated.previous_version == "0.1.0"
    assert activated.pending_version == "0.2.0"

    manager.rollback(transaction.transaction_id)

    rolled_back = store.load()
    assert rolled_back.active_version == "0.1.0"
    assert rolled_back.pending_version is None
    assert not (paths.versions_dir / "0.2.0" / "module.json").exists()
    assert not (paths.versions_dir / "0.2.0" / "app_entry.py").exists()


def test_new_launcher_activates_module_after_legacy_helper_swap(
    tmp_path: Path,
) -> None:
    paths = RuntimePaths(tmp_path)
    paths.ensure()
    store = StateStore(paths.state_file)
    store.bootstrap("0.1.0")
    module = paths.versions_dir / "0.2.0"
    module.mkdir()
    (module / "module.json").write_text(
        json.dumps(
            {
                "version": "0.2.0",
                "api_version": 1,
                "entrypoint": "app_entry.py:create_application",
            }
        ),
        encoding="utf-8",
    )
    (module / "app_entry.py").write_text(
        "def create_application(context): pass", encoding="utf-8"
    )
    transaction_id = "legacy-transaction"
    paths.update_data_dir.mkdir(parents=True, exist_ok=True)
    (paths.update_data_dir / "transaction.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "transaction_id": transaction_id,
                "version": "0.2.0",
                "stage": "swapped",
                "staging_path": str(tmp_path / "stage"),
                "backup_path": str(tmp_path / "backup"),
                "files": [],
                "completed": [],
                "error": None,
            }
        ),
        encoding="utf-8",
    )

    _activate_confirmed_full_update_module(paths, store, transaction_id)

    state = store.load()
    assert state.active_version == "0.2.0"
    assert state.previous_version == "0.1.0"
    assert state.pending_version == "0.2.0"


@pytest.mark.skipif(os.name != "nt", reason="Windows process wait regression")
def test_full_update_helper_waits_without_terminating_parent_process() -> None:
    process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(0.2)"])

    _wait_for_parent(process.pid, timeout_seconds=5)

    assert process.wait(timeout=1) == 0


def test_defer_windows_full_update_rollback_copies_and_starts_helper(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import signriver_launcher.main as launcher_main

    install = tmp_path / "install"
    cache = tmp_path / "cache"
    install.mkdir()
    executable = install / "launcher.exe"
    executable.write_bytes(b"new launcher")
    paths = RuntimePaths(
        install,
        install,
        host_platform=HostPlatform.WINDOWS,
        cache_root=cache,
    )
    calls: list[tuple[list[str], dict[str, object]]] = []

    monkeypatch.setattr(launcher_main.sys, "platform", "win32")
    monkeypatch.setattr(launcher_main.sys, "frozen", True, raising=False)
    monkeypatch.setattr(launcher_main.sys, "executable", str(executable))
    monkeypatch.setattr(
        "subprocess.Popen",
        lambda args, **kwargs: calls.append((args, kwargs)),
    )

    assert _defer_windows_full_update_rollback(paths, "transaction-1") is True

    helper = cache / "update-helpers" / "rollback-transaction-1.exe"
    assert helper.read_bytes() == b"new launcher"
    assert len(calls) == 1
    command, kwargs = calls[0]
    assert command == [
        str(helper),
        "--rollback-full-update",
        str(install),
        "transaction-1",
        str(os.getpid()),
        str(install),
        "windows",
        str(cache),
    ]
    assert kwargs["cwd"] == install
    assert kwargs["stdin"] == subprocess.DEVNULL
    assert kwargs["stdout"] == subprocess.DEVNULL
    assert kwargs["stderr"] == subprocess.DEVNULL
    assert kwargs["env"]["PYINSTALLER_RESET_ENVIRONMENT"] == "1"


def test_rollback_full_update_waits_rolls_back_and_starts_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import signriver_launcher.full_update_helper as helper_module

    install = tmp_path / "install"
    cache = tmp_path / "cache"
    install.mkdir()
    helper_executable = cache / "update-helpers" / "rollback-transaction-1.exe"
    restored_executable = (
        install
        / RuntimePaths(
            install, install, host_platform=HostPlatform.WINDOWS
        ).launcher_relative_path
    )
    waited: list[int] = []
    rolled_back: list[str] = []
    calls: list[tuple[list[str], dict[str, object]]] = []

    class FakeManager:
        def __init__(self, paths: RuntimePaths) -> None:
            assert paths.root == install.resolve()
            assert paths.install_root == install.resolve()
            assert paths.cache_dir == cache.resolve()

        def rollback(self, transaction_id: str) -> None:
            rolled_back.append(transaction_id)

    monkeypatch.setattr(helper_module, "_wait_for_parent", waited.append)
    monkeypatch.setattr(helper_module, "FullUpdateManager", FakeManager)
    monkeypatch.setattr(helper_module.sys, "frozen", True, raising=False)
    monkeypatch.setattr(helper_module.sys, "executable", str(helper_executable))
    monkeypatch.setattr(
        helper_module.subprocess,
        "Popen",
        lambda args, **kwargs: calls.append((args, kwargs)),
    )

    rollback_full_update(
        install,
        "transaction-1",
        1234,
        install_root=install,
        platform="windows",
        cache_root=cache,
    )

    assert waited == [1234]
    assert rolled_back == ["transaction-1"]
    assert len(calls) == 1
    command, kwargs = calls[0]
    assert command == [
        str(restored_executable),
        "--cleanup-full-update-helper",
        str(helper_executable),
        str(os.getpid()),
    ]
    assert kwargs["cwd"] == install
    assert kwargs["stdin"] == subprocess.DEVNULL
    assert kwargs["stdout"] == subprocess.DEVNULL
    assert kwargs["stderr"] == subprocess.DEVNULL
    assert kwargs["env"]["PYINSTALLER_RESET_ENVIRONMENT"] == "1"


def test_cleanup_full_update_helper_waits_deletes_and_restarts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import signriver_launcher.full_update_helper as helper_module

    install = tmp_path / "install"
    helper_dir = tmp_path / "cache" / "update-helpers"
    install.mkdir()
    helper_dir.mkdir(parents=True)
    helper_executable = helper_dir / "rollback-transaction-1.exe"
    helper_executable.write_bytes(b"helper")
    restored_executable = install / "launcher.exe"
    waited: list[int] = []
    calls: list[tuple[list[str], dict[str, object]]] = []

    monkeypatch.setattr(helper_module, "_wait_for_parent", waited.append)
    monkeypatch.setattr(helper_module.sys, "frozen", True, raising=False)
    monkeypatch.setattr(helper_module.sys, "executable", str(restored_executable))
    monkeypatch.setattr(
        helper_module.subprocess,
        "Popen",
        lambda args, **kwargs: calls.append((args, kwargs)),
    )

    cleanup_full_update_helper(helper_executable, 5678)

    assert waited == [5678]
    assert not helper_executable.exists()
    assert not helper_dir.exists()
    assert len(calls) == 1
    command, kwargs = calls[0]
    assert command == [str(restored_executable)]
    assert kwargs["cwd"] == install
    assert kwargs["stdin"] == subprocess.DEVNULL
    assert kwargs["stdout"] == subprocess.DEVNULL
    assert kwargs["stderr"] == subprocess.DEVNULL
    assert kwargs["env"]["PYINSTALLER_RESET_ENVIRONMENT"] == "1"


def test_frozen_child_environment_preserves_normal_python_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import signriver_launcher.full_update_helper as helper_module

    monkeypatch.delattr(helper_module.sys, "frozen", raising=False)
    monkeypatch.delenv("PYINSTALLER_RESET_ENVIRONMENT", raising=False)
    monkeypatch.setenv("SIGNRIVER_TEST_ENVIRONMENT", "preserved")

    environment = frozen_child_environment()

    assert environment["SIGNRIVER_TEST_ENVIRONMENT"] == "preserved"
    assert "PYINSTALLER_RESET_ENVIRONMENT" not in environment
