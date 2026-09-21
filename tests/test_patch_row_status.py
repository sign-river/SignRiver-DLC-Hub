"""补丁工具的行状态只依赖游戏目录与安装记录，不依赖下载缓存快照。

``patch_row_status`` 是模块级纯函数，UI 类本身需要 Tk 上下文，因此用
``ast`` 抽取该函数（连同两个状态表常量）在隔离命名空间里执行后测试。
"""
from __future__ import annotations

import ast
from pathlib import Path

APP_ENTRY = Path(__file__).parents[1] / "app" / "versions" / "0.1.0" / "app_entry.py"
SOURCE = APP_ENTRY.read_text(encoding="utf-8")
MODULE = ast.parse(SOURCE)
CONSTANTS = {"PATCH_ROW_DOWNLOAD_STATE_TEXT", "PATCH_ROW_DOWNLOAD_FAILURE_STATES"}


def _load_patch_row_status():
    body = [
        item for item in MODULE.body
        if (
            isinstance(item, ast.FunctionDef)
            and item.name == "patch_row_status"
        )
        or (
            isinstance(item, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id in CONSTANTS
                for target in item.targets
            )
        )
    ]
    namespace: dict = {}
    exec(  # noqa: S102
        compile(ast.Module(body=body, type_ignores=[]), APP_ENTRY, "exec"),
        namespace,
    )
    return namespace["patch_row_status"]


PATCH_ROW_STATUS = _load_patch_row_status()


def _status(**overrides) -> tuple[str, str]:
    base: dict = {
        "labels": ("steam_api64.dll",),
        "installed": False,
        "audit_healthy": False,
        "audit_known": False,
        "audit_problems": frozenset(),
        "download_state": None,
        "cached_ready": False,
    }
    base.update(overrides)
    return PATCH_ROW_STATUS(**base)


def test_installed_patch_stays_healthy_when_download_cache_is_gone() -> None:
    """重新打开客户端时，只要文件还在游戏目录就必须显示补丁正常。"""
    assert _status(
        installed=True, audit_healthy=True, audit_known=True, cached_ready=False
    ) == ("补丁正常", "success")
    assert _status(
        installed=True,
        audit_healthy=True,
        audit_known=True,
        download_state="ready",
        cached_ready=False,
    ) == ("补丁正常", "success")


def test_cache_state_is_only_reported_before_installation() -> None:
    assert _status() == ("尚未安装：补丁资源尚未下载", "muted")
    assert _status(download_state="ready", cached_ready=True) == (
        "尚未安装：补丁资源已就绪，可直接一键解锁",
        "muted",
    )
    assert _status(download_state="ready", cached_ready=False) == (
        "尚未安装：缓存资源已失效，请重新下载",
        "muted",
    )


def test_audit_problems_are_reported_per_file() -> None:
    problems = frozenset({"steam_api64.dll"})
    assert _status(installed=True, audit_known=True, audit_problems=problems) == (
        "补丁不完整：部分文件缺失或被修改",
        "danger",
    )
    assert _status(audit_known=True, audit_problems=problems) == (
        "补丁已失效：文件不在游戏目录",
        "danger",
    )
    # 记录里其它文件的问题不应牵连这一行。
    assert _status(
        installed=True,
        audit_healthy=True,
        audit_known=True,
        audit_problems=frozenset({"cream_api.ini"}),
    ) == ("补丁正常", "success")


def test_installed_without_receipt_only_states_the_record_is_missing() -> None:
    """缺少安装记录只做陈述，不引导用户去点一键修复。"""
    assert _status(installed=True, audit_known=False) == (
        "已写入：缺少安装记录",
        "muted",
    )


def test_download_states_keep_live_feedback() -> None:
    assert _status(download_state="queued") == ("补丁等待下载", "muted")
    assert _status(download_state="downloading") == ("补丁下载中", "muted")
    assert _status(download_state="paused") == ("补丁已暂停", "muted")
    assert _status(download_state="corrupt") == ("补丁异常：校验未通过", "danger")
    assert _status(download_state="failed") == ("补丁下载失败", "danger")
    assert _status(download_state="unexpected") == ("补丁处理中", "muted")


def test_installed_patch_is_not_reported_with_cache_wording() -> None:
    """用户反馈的那句“缓存文件不可用”不应再出现。"""
    assert "缓存文件不可用" not in SOURCE
