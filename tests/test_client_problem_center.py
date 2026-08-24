from __future__ import annotations

import importlib.util
import sys
import types
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from signriver_common.problems import (
    ProblemAction,
    ProblemCategory,
    ProblemCode,
    ProblemReport,
    ProblemSeverity,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
VERSION_ROOT = PROJECT_ROOT / "app" / "versions" / "0.1.0"


@pytest.fixture(scope="module")
def app_module():
    package_name = "_signriver_client_behavior"
    package = types.ModuleType(package_name)
    package.__path__ = [str(VERSION_ROOT)]
    sys.modules[package_name] = package
    spec = importlib.util.spec_from_file_location(
        f"{package_name}.app_entry", VERSION_ROOT / "app_entry.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _app(app_module):
    app = app_module.DlcHubApplication.__new__(app_module.DlcHubApplication)
    app.context = SimpleNamespace(
        app_version="0.2.0",
        launcher_version="0.2.0",
        logger=Mock(),
        paths=SimpleNamespace(
            platform="windows",
            data=Path("data"),
            cache=Path("cache"),
        ),
    )
    return app


def _asset(name: str, data: bytes, *, digest: str | None = None):
    return SimpleNamespace(
        name=name,
        download_url=f"https://example.invalid/{name}",
        size_bytes=len(data),
        sha256=digest if digest is not None else sha256(data).hexdigest(),
    )


def _report(*, actions: tuple[ProblemAction, ...]) -> ProblemReport:
    return ProblemReport.create(
        code=ProblemCode.APP_UNEXPECTED,
        category=ProblemCategory.APPLICATION,
        severity=ProblemSeverity.ERROR,
        stage="test",
        summary="test",
        suggestion="test",
        platform="windows",
        allowed_actions=actions,
    )


def test_patch_download_rejects_bundle_with_missing_sha256(app_module) -> None:
    app = _app(app_module)
    valid = _asset("valid.dll", b"valid")
    missing = _asset("missing.dll", b"missing", digest=None)
    missing.sha256 = None
    app.patch_bundle = SimpleNamespace(
        unlocker_dll=missing,
        original_backup_dll=valid,
        appinfo_json=_asset("appinfo.json", b"{}"),
    )
    app.download_queue = Mock()
    app._record_patch_problem = Mock()
    app._on_patch_workflow_failed = Mock()

    app._start_patch_downloads()

    app.download_queue.enqueue.assert_not_called()
    app._record_patch_problem.assert_called_once()
    assert app._record_patch_problem.call_args.kwargs["code"] is ProblemCode.PATCH_MISSING_HASH
    app._on_patch_workflow_failed.assert_called_once()


def test_patch_download_specs_accept_legacy_original_backup_role(app_module) -> None:
    app = _app(app_module)
    unlocker = _asset("unlocker.dll", b"unlocker")
    backup = _asset("original.dll", b"original")
    metadata = _asset("appinfo.json", b"{}")
    app.patch_bundle = SimpleNamespace(
        unlocker_dll=unlocker,
        original_backup_dll=backup,
        appinfo_json=metadata,
    )
    app.patch_task_roles = {
        "patch:unlocker": "unlocker_dll",
        "patch:backup": "original_backup_dll",
        "patch:metadata": "appinfo_json",
    }
    app.cartridge = SimpleNamespace(
        adapter=SimpleNamespace(descriptor=SimpleNamespace(game_id="game"))
    )

    specs = app._patch_download_specs()

    assert [spec.filename for spec in specs] == [
        "unlocker.dll", "original.dll", "appinfo.json",
    ]
    assert app._patch_asset_for("patch:backup") is backup


def test_ready_patch_with_missing_cache_is_forgotten_and_requeued(
    app_module, tmp_path: Path
) -> None:
    app = _app(app_module)
    app.patch_bundle = object()
    app._patch_assets_missing_hash = Mock(return_value=())
    spec = app_module.DownloadSpec(
        task_id="patch:unlocker",
        url="https://example.invalid/unlocker.dll",
        filename="unlocker.dll",
        game_id="game",
        expected_sha256="a" * 64,
    )
    snapshot = SimpleNamespace(
        spec=spec,
        state=app_module.DownloadState.READY,
        result_path=tmp_path / "quarantined.dll",
    )
    app._patch_download_specs = Mock(return_value=(spec,))
    app._patch_snapshots_by_task = Mock(return_value={spec.task_id: snapshot})
    future = Mock()
    app.download_queue = Mock()
    app.download_queue.enqueue.return_value = future
    app.catalog_preview = Mock()
    app.window = Mock()
    app._download_finished = Mock()
    app._set_batch_download_state = Mock()

    app._start_patch_downloads()

    app.download_queue.forget.assert_called_once_with((spec.task_id,))
    app.download_queue.enqueue.assert_called_once_with(spec)
    future.add_done_callback.assert_called_once_with(app._download_finished)
    assert app.patch_task_ids == (spec.task_id,)


def test_patch_asset_verification_rechecks_size_and_sha256(
    app_module, tmp_path: Path
) -> None:
    path = tmp_path / "asset.bin"
    path.write_bytes(b"actual")

    wrong_size = _asset("asset.bin", b"actual")
    wrong_size.size_bytes += 1
    with pytest.raises(app_module._PatchAssetVerificationError) as size_error:
        app_module.DlcHubApplication._verify_patch_asset(path, wrong_size)
    assert size_error.value.code is ProblemCode.PKG_SIZE_MISMATCH

    wrong_hash = _asset("asset.bin", b"actual", digest="0" * 64)
    with pytest.raises(app_module._PatchAssetVerificationError) as hash_error:
        app_module.DlcHubApplication._verify_patch_asset(path, wrong_hash)
    assert hash_error.value.code is ProblemCode.PKG_HASH_MISMATCH
    assert hash_error.value.actual_sha256 == sha256(b"actual").hexdigest()


def test_integrity_failure_never_calls_patch_engine_apply(
    app_module, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    app = _app(app_module)
    app.current_installation = SimpleNamespace(root=tmp_path, game_id="game")
    good_data = b"good"
    bad_data = b"evil"
    good_path = tmp_path / "good.dll"
    backup_path = tmp_path / "backup.dll"
    metadata_path = tmp_path / "appinfo.json"
    good_path.write_bytes(bad_data)
    backup_path.write_bytes(good_data)
    metadata_path.write_bytes(b"{}")
    unlocker = _asset("good.dll", good_data)
    backup = _asset("backup.dll", good_data)
    metadata = _asset("appinfo.json", b"{}")
    app.patch_bundle = SimpleNamespace(
        unlocker_dll=unlocker,
        original_backup_dll=backup,
        appinfo_json=metadata,
    )
    app.patch_engine = Mock()
    app.patch_task_roles = {
        "patch:unlocker": "unlocker_dll",
        "patch:backup": "original_backup_dll",
        "patch:metadata": "appinfo_json",
    }
    app.download_queue = Mock()
    app.patch_task_ids = tuple(app.patch_task_roles)
    app.catalog_preview = Mock()
    app._set_batch_download_state = Mock()
    app._record_patch_problem = Mock()
    app._on_patch_workflow_failed = Mock()
    app._post_ui = lambda callback: callback()

    class ImmediateThread:
        def __init__(self, *, target, daemon):
            self.target = target

        def start(self) -> None:
            self.target()

    monkeypatch.setattr(app_module.threading, "Thread", ImmediateThread)

    app._apply_patch_after_download(
        {
            "unlocker_dll": good_path,
            "original_backup_dll": backup_path,
            "appinfo_json": metadata_path,
        }
    )

    app.patch_engine.apply.assert_not_called()
    assert app._record_patch_problem.call_args.kwargs["code"] is ProblemCode.PKG_HASH_MISMATCH
    app._on_patch_workflow_failed.assert_called_once()


def test_post_apply_missing_file_restores_original_and_records_security_problem(
    app_module, tmp_path: Path
) -> None:
    app = _app(app_module)
    app.current_installation = SimpleNamespace(root=tmp_path)
    app.patch_profile = SimpleNamespace(unlocker_dll_name="unlocker.dll")
    app.patch_engine = Mock()
    app.patch_engine.audit_recorded.return_value = SimpleNamespace(
        health=app_module.PatchHealth.MODIFIED,
        missing=("unlocker.dll",),
        modified=(),
    )
    app._record_patch_problem = Mock()
    app._on_patch_workflow_failed = Mock()

    app._on_patch_applied(SimpleNamespace())

    app.patch_engine.restore_original.assert_called_once_with(tmp_path)
    assert (
        app._record_patch_problem.call_args.kwargs["code"]
        is ProblemCode.PATCH_SECURITY_INTERFERENCE_SUSPECTED
    )
    app._on_patch_workflow_failed.assert_called_once()


def test_problem_action_rejects_non_allowlisted_action(app_module) -> None:
    app = _app(app_module)
    app._open_path = Mock()
    report = _report(actions=(ProblemAction.COPY_DETAILS,))

    app._execute_problem_action(report, ProblemAction.OPEN_LOG_DIRECTORY)
    app._execute_problem_action(report, "https://attacker.invalid/command")

    app._open_path.assert_not_called()
    assert app.context.logger.warning.call_count == 2


def test_windows_security_failure_shows_manual_navigation(
    app_module, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = _app(app_module)
    app.window = object()
    report = _report(actions=(ProblemAction.OPEN_WINDOWS_SECURITY,))
    warning = Mock()
    monkeypatch.setattr(app_module.webbrowser, "open", lambda _url: False)
    monkeypatch.setattr(app_module.messagebox, "showwarning", warning)

    app._execute_problem_action(report, ProblemAction.OPEN_WINDOWS_SECURITY)

    warning.assert_called_once()
    assert "Windows 安全中心" in warning.call_args.args[1]
    assert "保护历史记录" in warning.call_args.args[1]


@pytest.mark.parametrize("platform", ["macos", "steamos"])
def test_non_windows_problem_does_not_offer_windows_security_action(
    app_module, platform: str
) -> None:
    app = _app(app_module)
    app.context.paths.platform = platform
    app._record_problem = lambda report: report

    report = app._record_patch_problem(
        code=ProblemCode.PATCH_SECURITY_INTERFERENCE_SUSPECTED,
        stage="verify",
        summary="test",
        suggestion="test",
    )

    assert ProblemAction.OPEN_WINDOWS_SECURITY not in report.allowed_actions
    assert ProblemAction.OPEN_MICROSOFT_FALSE_POSITIVE in report.allowed_actions


def test_problem_store_failure_does_not_reverse_successful_patch_apply(
    app_module, tmp_path: Path
) -> None:
    app = _app(app_module)
    app.current_installation = SimpleNamespace(root=tmp_path)
    app.patch_engine = Mock()
    app.patch_engine.audit_recorded.return_value = SimpleNamespace(
        health=app_module.PatchHealth.HEALTHY,
        missing=(),
        modified=(),
    )
    app.problem_store = Mock()
    app.problem_store.resolve_matching.side_effect = OSError("store unavailable")
    app.patch_task_roles = {"patch:unlocker": "unlocker_dll"}
    app.patch_task_ids = ("patch:unlocker",)
    app.patch_workflow_state = "applying"
    app.catalog_preview = Mock()
    app._update_problem_badge = Mock()
    app._notify = Mock()
    app.repair_workflow_active = False
    app.pending_dlc_batch_task_ids = ()
    app.catalog_entries = ()
    app._set_batch_download_state = Mock()
    app._maybe_finish_unlock_workflow = Mock()
    result = SimpleNamespace(
        backup_created=False,
        backup_replaced=False,
        unlocker_replaced=False,
        ini_written=False,
    )

    app._on_patch_applied(result)

    assert app.patch_workflow_state == "idle"
    app._notify.assert_called_once()
    app._maybe_finish_unlock_workflow.assert_called_once()
    app.context.logger.exception.assert_called_with(
        "Unable to resolve patch problems after successful apply"
    )
