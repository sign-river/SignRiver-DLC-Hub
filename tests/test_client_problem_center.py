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


def test_problem_record_titles_use_the_available_card_width() -> None:
    source = (VERSION_ROOT / "app_entry.py").read_text(encoding="utf-8")

    assert "def update_title_wraplength(event, label=title) -> None:" in source
    assert "available_width = int(event.width / scaling) - 24" in source
    assert "wraplength = max(1, available_width)" in source
    assert 'if label.cget("wraplength") != wraplength:' in source
    assert "label.configure(wraplength=wraplength)" in source
    assert 'row.bind("<Configure>", update_title_wraplength)' in source


def test_problem_detail_titles_are_left_aligned_and_resize_safely() -> None:
    source = (VERSION_ROOT / "app_entry.py").read_text(encoding="utf-8")

    assert "detail_title = ctk.CTkLabel(" in source
    assert 'justify="left"' in source
    assert "def update_detail_title_wraplength(event, label=detail_title) -> None:" in source
    assert 'header.bind("<Configure>", update_detail_title_wraplength)' in source


def test_patch_download_allows_bundle_with_missing_sha256(app_module) -> None:
    app = _app(app_module)
    valid = _asset("valid.dll", b"valid")
    missing = _asset("missing.dll", b"missing", digest=None)
    missing.sha256 = None
    app.patch_bundle = SimpleNamespace(
        unlocker_dll=missing,
        original_backup_dll=valid,
        appinfo_json=_asset("appinfo.json", b"{}"),
    )
    app.patch_task_roles = {
        "patch:unlocker": "unlocker_dll",
        "patch:backup": "original_backup_dll",
        "patch:metadata": "appinfo_json",
    }
    app.cartridge = SimpleNamespace(
        adapter=SimpleNamespace(descriptor=SimpleNamespace(game_id="game"))
    )
    app.download_queue = Mock()
    app._patch_snapshots_by_task = Mock(return_value={})
    future = Mock()
    app.download_queue.enqueue.return_value = future
    app.catalog_preview = Mock()
    app.window = Mock()
    app._record_patch_problem = Mock()
    app._on_patch_workflow_failed = Mock()
    app._set_batch_download_state = Mock()

    app._start_patch_downloads()

    assert app.download_queue.enqueue.call_count == 3
    first_spec = app.download_queue.enqueue.call_args_list[0].args[0]
    assert first_spec.expected_sha256 is None
    app._record_patch_problem.assert_not_called()
    app._on_patch_workflow_failed.assert_not_called()


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

    no_hash = _asset("asset.bin", b"actual")
    no_hash.sha256 = None
    assert app_module.DlcHubApplication._verify_patch_asset(path, no_hash) is None


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


def test_unlock_success_explains_that_the_patch_was_installed_this_run(app_module, monkeypatch) -> None:
    app = _app(app_module)
    app.unlock_workflow_active = True
    app.unlock_patch_applied_this_run = True
    app.repair_workflow_active = False
    app.patch_workflow_state = "idle"
    app.batch_download_state = "idle"
    app.auto_install_worker_running = False
    app.current_installation = SimpleNamespace(root=Path("game"))
    app.unlock_requested_dlc_ids = ()
    app.unlock_failed_dlc_ids = set()
    app.patch_engine = Mock()
    app.patch_engine.audit_recorded.return_value = SimpleNamespace(
        health=app_module.PatchHealth.HEALTHY
    )
    app._refresh_installed_dlc_paths = Mock()
    app._uses_built_in_dlc_delivery = Mock(return_value=False)
    app.cartridge = SimpleNamespace(
        adapter=SimpleNamespace(descriptor=SimpleNamespace(display_name="群星 (Stellaris)"))
    )
    app.catalog_preview = Mock()
    app._notify = Mock()
    app.window = Mock()
    showinfo = Mock()
    monkeypatch.setattr(app_module.messagebox, "showinfo", showinfo)

    app._maybe_finish_unlock_workflow()

    assert showinfo.call_args.args[1] == (
        "群星 (Stellaris) 的补丁已在本次操作中下载并安装。"
        "当前未选择需要额外安装的 DLC。"
    )
    assert app.unlock_patch_applied_this_run is False


def test_quick_check_replaces_a_tool_result_without_adding_a_second_row(app_module) -> None:
    app = _app(app_module)
    app.quick_check_lines = ["一键排错结果", "", "正在检查常见环境问题……", ""]
    app.quick_check_results = []

    result_index = app._add_quick_check_result("安全软件：正在检查……")
    app._replace_quick_check_result(
        result_index,
        "安全软件：已检测到 Windows Defender。",
        tool_detail_action=lambda: None,
    )

    assert len(app.quick_check_results) == 1
    assert app.quick_check_results[0][0] == "安全软件：已检测到 Windows Defender。"
    assert callable(app.quick_check_results[0][2])
    assert app.quick_check_lines[-1] == "1. 安全软件：已检测到 Windows Defender。"


def test_security_quick_check_updates_one_row_and_opens_cached_tool_detail(
    app_module, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = _app(app_module)
    product = SimpleNamespace(name="Windows Defender")
    app.quick_check_lines = ["一键排错结果", "", "正在检查常见环境问题……", ""]
    app.quick_check_results = []
    app.quick_check_running = True
    app.quick_check_paused = False
    app._render_quick_check_output = Mock()
    app._advance_quick_check = Mock()
    app._post_ui = lambda callback: callback()
    app.window = SimpleNamespace(after=lambda _delay, callback: callback())
    app._show_page = Mock()
    app._render_security_products = Mock()

    class ImmediateThread:
        def __init__(self, *, target, daemon):
            self.target = target

        def start(self) -> None:
            self.target()

    monkeypatch.setattr(app_module.threading, "Thread", ImmediateThread)
    monkeypatch.setattr(app_module, "discover_security_products", lambda: (product,))

    app._quick_check_security_products()

    assert len(app.quick_check_results) == 1
    text, solution_id, detail_action = app.quick_check_results[0]
    assert text == "安全软件：已检测到 1 个产品。"
    assert solution_id is None
    assert callable(detail_action)
    detail_action()
    app._show_page.assert_called_once_with("常用工具")
    app._render_security_products.assert_called_once_with((product,))


def test_open_mode_quick_check_tool_keeps_one_row_with_detail_action(app_module) -> None:
    app = _app(app_module)
    app.quick_check_lines = ["一键排错结果", "", "正在检查常见环境问题……", ""]
    app.quick_check_results = []
    tool = SimpleNamespace(
        run_mode="open",
        title="诊断工具",
        quick_check_problem_guide="update-module-basics",
    )
    app._show_page = Mock()
    app._show_guide_tool_detail = Mock()

    app._quick_check_declared_tool(tool)

    assert len(app.quick_check_results) == 1
    _, solution_id, detail_action = app.quick_check_results[0]
    assert solution_id == "update-module-basics"
    assert callable(detail_action)
    detail_action()
    app._show_page.assert_called_once_with("常用工具")
    app._show_guide_tool_detail.assert_called_once_with(tool)


def test_gui_callback_exception_records_patch_context_and_solution(app_module) -> None:
    app = _app(app_module)
    app.current_page = "常用工具"
    app.gui_operation_context = "补丁工具：重新下载"
    app.tool_center_detail_title = Mock()
    app.tool_center_detail_title.cget.return_value = "补丁工具"
    app._record_problem = Mock(side_effect=lambda report: report)

    try:
        raise KeyError("original_backup_dll")
    except KeyError as error:
        app._report_gui_callback_exception(type(error), error, error.__traceback__)

    report = app._record_problem.call_args.args[0]
    assert report.code is ProblemCode.APP_GUI_CALLBACK_FAILED
    assert report.summary == "补丁工具数据不完整，无法完成当前界面操作"
    assert report.task_id == "patch-tool"
    assert "触发页面：常用工具" in report.technical_details
    assert "操作上下文：补丁工具：重新下载" in report.technical_details
    assert "KeyError" in report.technical_details
    app._open_solution_article = Mock()
    app._open_problem_solution(report)
    app._open_solution_article.assert_called_once_with("patch-assets-missing")


def test_gui_callback_hook_is_installed(app_module) -> None:
    app = _app(app_module)
    app.window = SimpleNamespace()

    app._install_gui_exception_handler()

    assert app.window.report_callback_exception == app._report_gui_callback_exception


def test_catalog_network_failures_are_suppressed_until_repeated(app_module) -> None:
    app = _app(app_module)
    app.transient_network_failures = {}
    app._record_problem = Mock(side_effect=lambda report: report)

    import ssl

    for _ in range(2):
        app._record_catalog_refresh_failure(
            ssl.SSLError("[SSL: UNEXPECTED_EOF_WHILE_READING] EOF"),
            cartridge_id="stellaris", source="gitlink",
        )
    app._record_problem.assert_not_called()

    app._record_catalog_refresh_failure(
        ssl.SSLError("[SSL: UNEXPECTED_EOF_WHILE_READING] EOF"),
        cartridge_id="stellaris", source="gitlink",
    )

    report = app._record_problem.call_args.args[0]
    assert report.code is ProblemCode.NET_TLS
    assert report.task_id == "catalog-refresh:stellaris:gitlink:NET-TLS"
    assert "连续失败次数：3" in report.technical_details
    assert app._solution_id_for_problem_code(report.code) == "network-basics"


def test_catalog_success_clears_transient_failure_and_resolves_record(app_module) -> None:
    app = _app(app_module)
    key = "catalog-refresh:stellaris:gitlink:NET-TLS"
    app.transient_network_failures = {key: 3}
    app.problem_store = Mock()

    app._clear_catalog_network_failures(
        cartridge_id="stellaris", source="gitlink"
    )

    assert app.transient_network_failures == {}
    app.problem_store.resolve_matching.assert_called_once_with(
        code=ProblemCode.NET_TLS, task_id=key
    )
