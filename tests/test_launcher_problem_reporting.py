from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from signriver_common.platforms import HostPlatform
from signriver_common.problems import ProblemCode, ProblemStore
from signriver_launcher.config import UpdateSettings
from signriver_launcher.errors import ModuleLoadError, PackageError
from signriver_launcher.full_update_helper import rollback_full_update
from signriver_launcher.models import ReleaseInfo
from signriver_launcher.paths import RuntimePaths
from signriver_launcher.problem_reporting import (
    record_launcher_problem,
    record_module_load_problem,
)
from signriver_launcher.state import StateStore
from signriver_launcher.updater import UpdateClient


def _runtime(tmp_path: Path) -> tuple[RuntimePaths, StateStore]:
    paths = RuntimePaths(tmp_path, host_platform=HostPlatform.WINDOWS)
    paths.ensure()
    store = StateStore(paths.state_file)
    store.bootstrap("0.1.0")
    return paths, store


def _release(kind: str = "module") -> ReleaseInfo:
    return ReleaseInfo(
        version="0.2.0",
        kind=kind,
        package_url="https://example.test/update.zip",
        sha256="a" * 64,
        size=123,
        min_launcher_version="0.1.0",
    )


def test_launcher_problem_is_readable_from_shared_store(tmp_path: Path) -> None:
    paths, _store = _runtime(tmp_path)

    report = record_module_load_problem(
        paths,
        error=ModuleLoadError("module failed"),
        app_version="0.2.0",
    )

    loaded = ProblemStore(paths.data_dir / "problems").get(report.event_id)
    assert loaded is not None
    assert loaded.code is ProblemCode.APP_MODULE_LOAD_FAILED
    assert loaded.app_version == "0.2.0"
    assert loaded.platform == "windows"


def test_problem_store_failure_does_not_replace_original_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import signriver_launcher.problem_reporting as reporting

    paths, _store = _runtime(tmp_path)
    original = PackageError("original failure")

    def fail_record(self, report):
        raise OSError("problem store unavailable")

    monkeypatch.setattr(reporting.ProblemStore, "record", fail_record)
    report = record_launcher_problem(
        paths,
        code=ProblemCode.APP_UNEXPECTED,
        category=reporting.ProblemCategory.APPLICATION,
        severity=reporting.ProblemSeverity.ERROR,
        stage="test",
        summary="test",
        suggestion="test",
        error=original,
    )

    assert report.code is ProblemCode.APP_UNEXPECTED
    assert "original failure" in report.technical_details


def test_update_download_failure_records_problem(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths, store = _runtime(tmp_path)
    client = UpdateClient(paths, UpdateSettings(), store, host_package_key="windows-x64")

    def fail_download(*_args, **_kwargs):
        raise OSError("network unavailable")

    monkeypatch.setattr(client, "_download", fail_download)
    with pytest.raises(OSError, match="network unavailable"):
        client.download(_release())

    reports = ProblemStore(paths.data_dir / "problems").list_reports()
    assert reports[0].code is ProblemCode.UPDATE_DOWNLOAD_FAILED
    assert reports[0].stage == "update.download"
    assert reports[0].expected_sha256 == "a" * 64


def test_update_install_failure_records_problem(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths, store = _runtime(tmp_path)
    client = UpdateClient(paths, UpdateSettings(), store, host_package_key="windows-x64")
    archive = tmp_path / "update.zip"
    archive.write_bytes(b"archive")
    monkeypatch.setattr(client, "download", lambda *_args, **_kwargs: archive)

    def fail_install(*_args, **_kwargs):
        raise PackageError("cannot install")

    monkeypatch.setattr(client, "install_archive", fail_install)
    with pytest.raises(PackageError, match="cannot install"):
        client.install(_release())

    reports = ProblemStore(paths.data_dir / "problems").list_reports()
    assert reports[0].code is ProblemCode.UPDATE_APPLY_FAILED
    assert reports[0].stage == "update.install_module"
    assert not archive.exists()


def test_detached_full_update_rollback_records_problem(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import signriver_launcher.full_update_helper as helper

    paths, _store = _runtime(tmp_path)
    captured: list[dict[str, object]] = []

    class FakeManager:
        def __init__(self, actual_paths: RuntimePaths) -> None:
            assert actual_paths.root == paths.root.resolve()

        def rollback(self, transaction_id: str):
            assert transaction_id == "transaction-1"
            return SimpleNamespace(version="0.2.0")

    monkeypatch.setattr(helper, "_wait_for_parent", lambda _pid: None)
    monkeypatch.setattr(helper, "FullUpdateManager", FakeManager)
    monkeypatch.setattr(
        helper,
        "record_update_problem",
        lambda *_args, **kwargs: captured.append(kwargs),
    )

    rollback_full_update(paths.root, "transaction-1", 123, restart=False)

    assert captured[0]["code"] is ProblemCode.UPDATE_ROLLED_BACK
    assert captured[0]["stage"] == "update.helper_rollback"
    assert captured[0]["target_version"] == "0.2.0"


def test_main_records_module_failure_and_automatic_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import signriver_launcher.main as launcher_main

    paths = RuntimePaths(tmp_path, host_platform=HostPlatform.WINDOWS)
    paths.ensure()
    for version in ("0.1.0", "0.2.0"):
        directory = paths.versions_dir / version
        directory.mkdir(parents=True)
        (directory / "module.json").write_text(
            json.dumps(
                {
                    "version": version,
                    "api_version": 1,
                    "entrypoint": "app_entry.py:create_application",
                }
            ),
            encoding="utf-8",
        )
        (directory / "app_entry.py").write_text("# test", encoding="utf-8")
    store = StateStore(paths.state_file)
    store.bootstrap("0.1.0")
    store.activate("0.2.0")

    class Application:
        def run(self) -> None:
            return None

    class Loader:
        def __init__(self, _versions_dir: Path) -> None:
            pass

        def create_application(self, version: str, _context):
            if version == "0.2.0":
                raise ModuleLoadError("new module failed")
            return Application()

    logger = logging.getLogger("test-launcher-problems")
    monkeypatch.setattr(launcher_main.RuntimePaths, "discover", lambda: paths)
    monkeypatch.setattr(launcher_main, "_configure_logging", lambda _path: logger)
    monkeypatch.setattr(
        launcher_main.UpdateSettings,
        "load",
        lambda *_args, **_kwargs: UpdateSettings(),
    )
    monkeypatch.setattr(launcher_main, "ModuleLoader", Loader)
    monkeypatch.setattr(
        launcher_main.HostContext,
        "create",
        lambda *_args, **_kwargs: object(),
    )
    monkeypatch.setattr(launcher_main, "_show_rollback_notice", lambda *_args: None)

    assert launcher_main.main([]) == 0

    reports = ProblemStore(paths.data_dir / "problems").list_reports()
    assert {report.code for report in reports} == {
        ProblemCode.APP_MODULE_LOAD_FAILED,
        ProblemCode.UPDATE_ROLLED_BACK,
    }
    assert store.load().active_version == "0.1.0"


def test_fatal_error_details_and_stderr_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import signriver_launcher.main as launcher_main

    paths, _store = _runtime(tmp_path)
    report = record_module_load_problem(
        paths,
        error=ModuleLoadError("module failed"),
        app_version="0.2.0",
    )
    monkeypatch.setitem(sys.modules, "tkinter", None)

    launcher_main._show_fatal_error("无法启动", report, paths.log_dir)

    output = capsys.readouterr().err
    assert "摘要：无法启动" in output
    assert f"错误码：{ProblemCode.APP_MODULE_LOAD_FAILED.value}" in output
    assert f"事件 ID：{report.event_id}" in output
