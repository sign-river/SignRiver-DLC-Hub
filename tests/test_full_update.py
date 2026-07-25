from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from signriver_launcher.errors import FullUpdateError
from signriver_launcher.full_update import FullUpdateManager
from signriver_launcher.models import ReleaseInfo
from signriver_launcher.paths import RuntimePaths


def _digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _archive(path: Path, version: str = "0.2.0", files: dict[str, bytes] | None = None) -> ReleaseInfo:
    files = files or {"launcher.exe": b"new launcher", "app/new.txt": b"new app"}
    manifest = {
        "schema_version": 1,
        "version": version,
        "files": [{"path": name, "size": len(value), "sha256": _digest(value)} for name, value in files.items()],
    }
    with zipfile.ZipFile(path, "w") as package:
        package.writestr("release-manifest.json", json.dumps(manifest))
        for name, value in files.items():
            package.writestr(name, value)
    data = path.read_bytes()
    return ReleaseInfo(version, "full", "https://example.test/full.zip", _digest(data), len(data), "0.1.0")


def test_full_update_swaps_only_manifest_owned_files_and_preserves_user_state(tmp_path: Path) -> None:
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
    assert (paths.data_dir / "settings.json").read_text(encoding="utf-8") == '{"keep": true}'
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


def test_full_update_confirmation_keeps_backup_for_later_cleanup(tmp_path: Path) -> None:
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
    assert (Path(transaction.backup_path) / "launcher.exe").read_bytes() == b"old launcher"
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


def test_full_update_allows_a_new_transaction_after_confirmation(tmp_path: Path) -> None:
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


def test_full_update_rejects_user_data_paths_without_touching_installation(tmp_path: Path) -> None:
    paths = RuntimePaths(tmp_path)
    paths.ensure()
    package = tmp_path / "unsafe.zip"
    release = _archive(package, files={"data/evil.txt": b"no"})

    with pytest.raises(FullUpdateError, match="cannot manage"):
        FullUpdateManager(paths).prepare(package, release)
    assert not (paths.data_dir / "evil.txt").exists()


def test_full_update_rejects_manifest_hash_mismatch_before_swapping(tmp_path: Path) -> None:
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
