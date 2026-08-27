from __future__ import annotations

import logging
import os
import shutil
import sys
import traceback
from logging.handlers import RotatingFileHandler
from pathlib import Path

from signriver_common.problems import (
    ProblemCategory,
    ProblemCode,
    ProblemReport,
    ProblemSeverity,
)

from .api import HostContext
from .config import UpdateSettings
from .errors import ConfigurationError, ModuleLoadError, PackageError, SignRiverError
from .loader import ModuleLoader
from .jsonio import read_json
from .models import ModuleMetadata
from .paths import RuntimePaths
from .problem_reporting import (
    record_launcher_problem,
    record_module_load_problem,
    record_update_problem,
)
from .state import StateStore
from .updater import UpdateClient
from .versioning import Version
from .full_update import FullUpdateManager
from .full_update_helper import (
    apply_full_update,
    cleanup_full_update_helper,
    frozen_child_environment,
    rollback_full_update,
)


def _configure_logging(log_dir: Path) -> logging.Logger:
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("signriver")
    logger.setLevel(logging.INFO)
    if logger.handlers:
        return logger
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )
    file_handler = RotatingFileHandler(
        log_dir / "launcher.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    if not getattr(sys, "frozen", False):
        console = logging.StreamHandler()
        console.setFormatter(formatter)
        logger.addHandler(console)
    return logger


def _bootstrap_state(paths: RuntimePaths, store: StateStore) -> None:
    if paths.state_file.exists():
        return
    installed: list[tuple[Version, str]] = []
    for directory in paths.versions_dir.iterdir():
        if not directory.is_dir():
            continue
        try:
            installed.append((Version.parse(directory.name), directory.name))
        except ValueError:
            continue
    if not installed:
        raise ConfigurationError("No application module is installed")
    store.bootstrap(max(installed)[1])


def _format_fatal_error_details(
    message: str, report: ProblemReport | None = None
) -> str:
    lines = [f"摘要：{message}"]
    if report is not None:
        lines.extend(
            (
                f"错误码：{report.code.value}",
                f"事件 ID：{report.event_id}",
                "",
                report.format_details(),
            )
        )
    return "\n".join(lines)


def _open_directory(path: Path) -> None:
    import subprocess

    resolved = path.resolve()
    if sys.platform == "win32":
        os.startfile(resolved)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(resolved)])
    else:
        subprocess.Popen(["xdg-open", str(resolved)])


def _show_fatal_error(
    message: str,
    report: ProblemReport | None = None,
    log_dir: Path | None = None,
) -> None:
    details = _format_fatal_error_details(message, report)
    try:
        import tkinter as tk

        root = tk.Tk()
        root.title("唏嘘南溪DLC一键解锁工具")
        root.resizable(False, False)
        frame = tk.Frame(root, padx=20, pady=18)
        frame.pack(fill="both", expand=True)
        tk.Label(
            frame,
            text="程序无法继续启动",
            font=("Microsoft YaHei UI", 14, "bold"),
            anchor="w",
        ).pack(fill="x")
        tk.Label(
            frame,
            text=message,
            justify="left",
            anchor="w",
            wraplength=520,
            pady=10,
        ).pack(fill="x")
        status = tk.StringVar(value="")

        def copy_details() -> None:
            root.clipboard_clear()
            root.clipboard_append(details)
            root.update_idletasks()
            status.set("详情已复制")

        def open_logs() -> None:
            if log_dir is None:
                return
            try:
                log_dir.mkdir(parents=True, exist_ok=True)
                _open_directory(log_dir)
            except Exception as error:
                status.set(f"无法打开日志目录：{error}")

        button_row = tk.Frame(frame)
        button_row.pack(fill="x", pady=(8, 0))
        tk.Button(button_row, text="复制详情", command=copy_details, width=12).pack(
            side="left"
        )
        if log_dir is not None:
            tk.Button(
                button_row, text="打开日志目录", command=open_logs, width=14
            ).pack(side="left", padx=(8, 0))
        tk.Button(button_row, text="退出", command=root.destroy, width=10).pack(
            side="right"
        )
        tk.Label(frame, textvariable=status, anchor="w", fg="#8a3b12").pack(
            fill="x", pady=(8, 0)
        )
        root.protocol("WM_DELETE_WINDOW", root.destroy)
        root.mainloop()
    except Exception:
        print(details, file=sys.stderr)


def format_rollback_notice(
    failed_version: str, rolled_back_version: str, reason: str
) -> str:
    """Compose the recovery notice shown after an automatic module rollback."""
    return (
        f"新版本模块 {failed_version} 启动失败，已自动回滚到 {rolled_back_version}。\n"
        f"失败原因：{reason}\n\n"
        "程序已用上一版本正常打开（启动器保持当前版本）。\n"
        "可在「设置」页重新点击检查更新，重新下载修复后的版本；\n"
        "若反复失败，请通过日志页导出诊断信息后反馈。"
    )


def _show_rollback_notice(
    failed_version: str, rolled_back_version: str, error: ModuleLoadError
) -> None:
    try:
        from tkinter import messagebox

        messagebox.showwarning(
            "唏嘘南溪DLC一键解锁工具",
            format_rollback_notice(failed_version, rolled_back_version, str(error)),
        )
    except Exception:
        print(
            format_rollback_notice(failed_version, rolled_back_version, str(error)),
            file=sys.stderr,
        )


def _find_usable_module(versions_dir: Path, excluded: set[str]) -> str | None:
    """Return the newest intact module directory that can still boot."""
    candidates: list[str] = []
    for directory in versions_dir.iterdir():
        if not directory.is_dir():
            continue
        name = directory.name
        try:
            Version.parse(name)
        except ValueError:
            continue
        if name in excluded:
            continue
        try:
            metadata = ModuleMetadata.from_dict(read_json(directory / "module.json"))
        except (OSError, ValueError, PackageError):
            continue
        if metadata.version != name:
            continue
        entrypoint = metadata.entrypoint.rsplit(":", 1)[0]
        if not (directory / entrypoint).is_file():
            continue
        candidates.append(name)
    if not candidates:
        return None
    return str(max(candidates, key=Version.parse))


def _activate_confirmed_full_update_module(
    paths: RuntimePaths,
    store: StateStore,
    transaction_id: str,
) -> None:
    """Activate a full-update module even when the swap used an older helper."""
    transaction = FullUpdateManager(paths).load()
    if (
        transaction is None
        or transaction.transaction_id != transaction_id
        or transaction.stage != "swapped"
    ):
        return
    module_root = paths.versions_dir / transaction.version
    metadata = ModuleMetadata.from_dict(read_json(module_root / "module.json"))
    entrypoint = metadata.entrypoint.rsplit(":", 1)[0]
    if (
        metadata.version != transaction.version
        or not (module_root / entrypoint).is_file()
    ):
        raise ModuleLoadError(
            "full update target module metadata does not match the transaction"
        )
    store.activate(transaction.version)


def _defer_windows_full_update_rollback(
    paths: RuntimePaths, transaction_id: str
) -> bool:
    """Start a detached rollback helper when this process locks the new EXE."""
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        return False
    import subprocess

    helper_dir = paths.cache_dir / "update-helpers"
    helper_dir.mkdir(parents=True, exist_ok=True)
    helper = helper_dir / f"rollback-{transaction_id}.exe"
    shutil.copy2(sys.executable, helper)
    subprocess.Popen(
        [
            str(helper),
            "--rollback-full-update",
            str(paths.root),
            transaction_id,
            str(os.getpid()),
            str(paths.install_root or paths.root),
            paths.platform.value,
            str(paths.cache_dir),
        ],
        cwd=paths.resources_root,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=frozen_child_environment(),
    )
    return True


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "--apply-full-update":
        if len(argv) not in {4, 7}:
            return 2
        apply_full_update(
            Path(argv[1]),
            argv[2],
            int(argv[3]),
            install_root=Path(argv[4]) if len(argv) == 7 else None,
            platform=argv[5] if len(argv) == 7 else None,
            cache_root=Path(argv[6]) if len(argv) == 7 else None,
        )
        return 0
    if argv and argv[0] == "--cleanup-full-update-helper":
        if len(argv) != 3:
            return 2
        cleanup_full_update_helper(Path(argv[1]), int(argv[2]))
        return 0
    if argv and argv[0] == "--rollback-full-update":
        if len(argv) not in {4, 7}:
            return 2
        rollback_full_update(
            Path(argv[1]),
            argv[2],
            int(argv[3]),
            install_root=Path(argv[4]) if len(argv) == 7 else None,
            platform=argv[5] if len(argv) == 7 else None,
            cache_root=Path(argv[6]) if len(argv) == 7 else None,
        )
        return 0
    confirm_transaction = None
    if argv and argv[0] == "--confirm-full-update":
        if len(argv) != 2:
            return 2
        confirm_transaction = argv[1]
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "SignRiver.DLCHub.1"
            )
        except Exception:
            pass
    paths = RuntimePaths.discover()
    paths.ensure()
    logger = _configure_logging(paths.log_dir)
    store = StateStore(paths.state_file)
    fatal_report: ProblemReport | None = None
    try:
        _bootstrap_state(paths, store)
        full_update_manager = FullUpdateManager(paths)
        full_update_manager.recover_pending()
        if confirm_transaction:
            try:
                _activate_confirmed_full_update_module(
                    paths, store, confirm_transaction
                )
            except (OSError, ValueError, SignRiverError) as error:
                transaction = full_update_manager.load()
                fatal_report = record_update_problem(
                    paths,
                    code=ProblemCode.UPDATE_APPLY_FAILED,
                    stage="update.confirm_activation",
                    error=error,
                    app_version=store.load().active_version,
                    target_version=transaction.version if transaction else None,
                    filename=None,
                    expected_sha256=None,
                    logger=logger,
                )
                if _defer_windows_full_update_rollback(paths, confirm_transaction):
                    return 1
                rolled_back = full_update_manager.rollback(confirm_transaction)
                record_update_problem(
                    paths,
                    code=ProblemCode.UPDATE_ROLLED_BACK,
                    stage="update.confirm_rollback",
                    error=error,
                    app_version=store.load().active_version,
                    target_version=rolled_back.version,
                    filename=None,
                    expected_sha256=None,
                    logger=logger,
                )
                raise
        settings = UpdateSettings.load(
            paths.update_config_file,
            defaults_path=paths.update_defaults_config_file,
            user_path=paths.user_update_config_file,
        )
        updater = UpdateClient(paths, settings, store)
        loader = ModuleLoader(paths.versions_dir)

        state = store.load()
        try:
            context = HostContext.create(
                state.active_version,
                paths.root,
                paths.data_dir,
                paths.cache_dir,
                updater,
                logger,
                paths.resources_root,
                paths.platform.value,
            )
            application = loader.create_application(state.active_version, context)
            store.mark_healthy(state.active_version)
            if confirm_transaction:
                FullUpdateManager(paths).confirm(confirm_transaction)
        except ModuleLoadError as error:
            fatal_report = record_module_load_problem(
                paths,
                error=error,
                app_version=state.active_version,
                logger=logger,
            )
            if confirm_transaction:
                transaction = FullUpdateManager(paths).load()
                record_update_problem(
                    paths,
                    code=ProblemCode.UPDATE_APPLY_FAILED,
                    stage="update.confirm_module_load",
                    error=error,
                    app_version=state.active_version,
                    target_version=transaction.version if transaction else None,
                    filename=None,
                    expected_sha256=None,
                    logger=logger,
                )
                if _defer_windows_full_update_rollback(paths, confirm_transaction):
                    logger.exception(
                        "New full-update module failed; deferred rollback to helper"
                    )
                    return 1
                rolled_back = FullUpdateManager(paths).rollback(confirm_transaction)
                record_update_problem(
                    paths,
                    code=ProblemCode.UPDATE_ROLLED_BACK,
                    stage="update.confirm_module_rollback",
                    error=error,
                    app_version=store.load().active_version,
                    target_version=rolled_back.version,
                    filename=None,
                    expected_sha256=None,
                    logger=logger,
                )
            failed_version = state.active_version
            if updater.prevent_module_fallback:
                raise ModuleLoadError(
                    f"{error}\n\n已按设置保留当前模块 v{failed_version}，未自动回退到旧版本。"
                    "请查看启动日志并修复当前模块后重试。"
                ) from error
            logger.exception("New module failed during initialization; rolling back")
            excluded = {failed_version, *state.bad_versions}
            fallback = _find_usable_module(paths.versions_dir, excluded)
            if fallback is None:
                raise ModuleLoadError(
                    f"{error}"
                    + "\n\n模块文件缺失或损坏，且没有可用版本可回退。"
                    + "请到「设置」页点击「检查更新」重新下载安装。"
                ) from error
            state = store.fallback_to(failed_version, fallback)
            if not confirm_transaction:
                record_update_problem(
                    paths,
                    code=ProblemCode.UPDATE_ROLLED_BACK,
                    stage="module.fallback",
                    error=error,
                    app_version=state.active_version,
                    target_version=failed_version,
                    filename=None,
                    expected_sha256=None,
                    logger=logger,
                )
            context = HostContext.create(
                state.active_version,
                paths.root,
                paths.data_dir,
                paths.cache_dir,
                updater,
                logger,
                paths.resources_root,
                paths.platform.value,
            )
            application = loader.create_application(state.active_version, context)
            _show_rollback_notice(failed_version, state.active_version, error)

        logger.info("Starting application module %s", state.active_version)
        application.run()
        return 0
    except (SignRiverError, OSError, ValueError) as error:
        logger.error("Fatal launcher error: %s\n%s", error, traceback.format_exc())
        if fatal_report is None:
            try:
                app_version = store.load().active_version
            except Exception:
                app_version = None
            if isinstance(error, ModuleLoadError):
                fatal_report = record_module_load_problem(
                    paths,
                    error=error,
                    app_version=app_version,
                    logger=logger,
                )
            else:
                fatal_report = record_launcher_problem(
                    paths,
                    code=ProblemCode.APP_UNEXPECTED,
                    category=ProblemCategory.APPLICATION,
                    severity=ProblemSeverity.CRITICAL,
                    stage="launcher.fatal",
                    summary="启动器发生致命错误",
                    suggestion="请打开日志目录或复制详情后联系开发者。",
                    error=error,
                    app_version=app_version,
                    logger=logger,
                )
        _show_fatal_error(str(error), fatal_report, paths.log_dir)
        return 1
