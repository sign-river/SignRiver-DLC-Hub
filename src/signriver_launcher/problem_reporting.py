"""Best-effort structured problem reporting for the launcher."""

from __future__ import annotations

import logging
import traceback

from signriver_common.problems import (
    ProblemAction,
    ProblemCategory,
    ProblemCode,
    ProblemReport,
    ProblemSeverity,
    ProblemStore,
)

from .constants import LAUNCHER_VERSION
from .paths import RuntimePaths


def record_launcher_problem(
    paths: RuntimePaths,
    *,
    code: ProblemCode,
    category: ProblemCategory,
    severity: ProblemSeverity,
    stage: str,
    summary: str,
    suggestion: str,
    error: BaseException | None = None,
    app_version: str | None = None,
    task_id: str | None = None,
    filename: str | None = None,
    expected_sha256: str | None = None,
    actual_sha256: str | None = None,
    logger: logging.Logger | None = None,
) -> ProblemReport:
    """Record a launcher problem without ever replacing the original failure."""
    details = ""
    if error is not None:
        details = "".join(traceback.format_exception(error)).strip() or str(error)
    report = ProblemReport.create(
        code=code,
        category=category,
        severity=severity,
        stage=stage,
        summary=summary,
        suggestion=suggestion,
        technical_details=details,
        app_version=app_version,
        launcher_version=LAUNCHER_VERSION,
        platform=paths.platform.value,
        task_id=task_id,
        filename=filename,
        expected_sha256=expected_sha256,
        actual_sha256=actual_sha256,
        allowed_actions=(
            ProblemAction.COPY_DETAILS,
            ProblemAction.OPEN_LOG_DIRECTORY,
            ProblemAction.EXPORT_DIAGNOSTICS,
            ProblemAction.MARK_RESOLVED,
            ProblemAction.DELETE,
        ),
    )
    try:
        return ProblemStore(paths.data_dir / "problems").record(report)
    except Exception:
        if logger is not None:
            logger.warning(
                "Unable to persist launcher problem %s (%s)",
                report.event_id,
                report.code.value,
                exc_info=True,
            )
        return report


def record_module_load_problem(
    paths: RuntimePaths,
    *,
    error: BaseException,
    app_version: str | None,
    stage: str = "module.load",
    logger: logging.Logger | None = None,
) -> ProblemReport:
    return record_launcher_problem(
        paths,
        code=ProblemCode.APP_MODULE_LOAD_FAILED,
        category=ProblemCategory.APPLICATION,
        severity=ProblemSeverity.CRITICAL,
        stage=stage,
        summary="应用模块加载失败",
        suggestion="启动器会尝试回滚到可用版本；若仍无法启动，请打开日志目录并反馈事件 ID。",
        error=error,
        app_version=app_version,
        task_id=f"module:{app_version}" if app_version else "module",
        logger=logger,
    )


def record_update_problem(
    paths: RuntimePaths,
    *,
    code: ProblemCode,
    stage: str,
    error: BaseException | None,
    app_version: str | None,
    target_version: str | None,
    filename: str | None,
    expected_sha256: str | None,
    logger: logging.Logger | None = None,
) -> ProblemReport:
    if code is ProblemCode.UPDATE_DOWNLOAD_FAILED:
        summary = "程序更新下载失败"
        suggestion = "请检查网络和下载源后重试；持续失败时打开问题中心导出诊断信息。"
    elif code is ProblemCode.UPDATE_ROLLED_BACK:
        summary = "程序更新已自动回滚"
        suggestion = "当前文件已恢复到更新前状态。请重新检查更新，持续失败时导出诊断信息。"
    else:
        summary = "程序更新应用失败"
        suggestion = "游戏文件未受影响。请重新检查更新，持续失败时打开日志目录。"
    return record_launcher_problem(
        paths,
        code=code,
        category=ProblemCategory.UPDATE,
        severity=(
            ProblemSeverity.WARNING
            if code is ProblemCode.UPDATE_ROLLED_BACK
            else ProblemSeverity.ERROR
        ),
        stage=stage,
        summary=summary,
        suggestion=suggestion,
        error=error,
        app_version=app_version,
        task_id=f"update:{target_version}" if target_version else "update",
        filename=filename,
        expected_sha256=expected_sha256,
        logger=logger,
    )


__all__ = [
    "record_launcher_problem",
    "record_module_load_problem",
    "record_update_problem",
]
