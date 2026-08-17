from __future__ import annotations

import errno
import json
import socket
import ssl
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.error import HTTPError

import pytest

from signriver_common.problems import (
    ProblemAction,
    ProblemCategory,
    ProblemCode,
    ProblemReport,
    ProblemSeverity,
    ProblemStatus,
    ProblemStore,
    build_problem_report,
    classify_exception,
    sanitize_technical_details,
)


def _report(*, when: datetime | None = None, task_id: str = "task-1") -> ProblemReport:
    return ProblemReport.create(
        code=ProblemCode.NET_TIMEOUT,
        category=ProblemCategory.NETWORK,
        severity=ProblemSeverity.ERROR,
        stage="connect",
        summary="连接超时",
        suggestion="重试",
        technical_details="TimeoutError: timed out",
        task_id=task_id,
        filename="package.zip",
        allowed_actions=(ProblemAction.RETRY_TASK, "not-allowed"),
        occurred_at=when,
    )


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (TimeoutError("timed out"), ProblemCode.NET_TIMEOUT),
        (socket.gaierror(-2, "getaddrinfo failed"), ProblemCode.NET_DNS),
        (ssl.SSLError("TLS handshake failed"), ProblemCode.NET_TLS),
        (HTTPError("https://example.invalid", 503, "unavailable", {}, None), ProblemCode.NET_HTTP),
        (PermissionError(errno.EACCES, "denied"), ProblemCode.FS_PERMISSION_DENIED),
        (OSError(errno.ENOSPC, "disk full"), ProblemCode.FS_DISK_FULL),
        (OSError(errno.EINVAL, "invalid argument"), ProblemCode.FS_INVALID_PATH),
        (ValueError("SHA-256 hash mismatch"), ProblemCode.PKG_HASH_MISMATCH),
        (RuntimeError("unknown"), ProblemCode.APP_UNEXPECTED),
    ],
)
def test_classify_exception(error: BaseException, expected: ProblemCode) -> None:
    assert classify_exception(error, stage="write").code is expected


def test_patch_file_disappearance_is_security_interference(tmp_path: Path) -> None:
    part = tmp_path / "patch.dll.part"
    result = classify_exception(
        FileNotFoundError(errno.ENOENT, "removed", part),
        stage="flush",
        purpose="patch_binary",
        temporary_path=part,
        write_started=True,
    )
    assert result.code is ProblemCode.PATCH_SECURITY_INTERFERENCE_SUSPECTED
    assert result.stop_retry is True
    assert "疑似" in result.summary


def test_patch_einval_requires_missing_temporary_file(tmp_path: Path) -> None:
    part = tmp_path / "patch.dll.part"
    part.write_bytes(b"still here")
    assert classify_exception(
        OSError(errno.EINVAL, "invalid argument"),
        stage="write", purpose="patch_binary", temporary_path=part, write_started=True,
    ).code is ProblemCode.FS_INVALID_PATH
    part.unlink()
    assert classify_exception(
        OSError(errno.EINVAL, "invalid argument"),
        stage="write", purpose="patch_binary", temporary_path=part, write_started=True,
    ).code is ProblemCode.PATCH_SECURITY_INTERFERENCE_SUSPECTED


def test_problem_report_drops_unknown_actions_and_paths() -> None:
    report = ProblemReport.from_dict({
        **_report().to_dict(),
        "filename": "../../unsafe/package.zip",
        "allowed_actions": ["retry_task", "run_arbitrary_command", "https://evil.invalid"],
    })
    assert report.filename == "package.zip"
    assert report.allowed_actions == (ProblemAction.RETRY_TASK,)


def test_problem_store_merges_duplicates_and_resolves(tmp_path: Path) -> None:
    store = ProblemStore(tmp_path / "problems")
    first = store.record(_report())
    second = store.record(_report())
    assert second.event_id == first.event_id
    assert second.retry_count == 1
    assert store.unresolved_count() == 1
    assert store.resolve_matching(task_id="task-1") == 1
    assert store.get(first.event_id).status is ProblemStatus.RESOLVED


def test_problem_store_skips_corrupt_records_and_writes_atomically(tmp_path: Path) -> None:
    directory = tmp_path / "problems"
    store = ProblemStore(directory)
    report = store.record(_report())
    (directory / "broken.json").write_text("{", encoding="utf-8")
    assert [item.event_id for item in store.list_reports()] == [report.event_id]
    assert not list(directory.glob("*.tmp"))
    payload = json.loads((directory / f"{report.event_id}.json").read_text(encoding="utf-8"))
    assert payload["event_id"] == report.event_id


def test_problem_store_prunes_by_age_and_count(tmp_path: Path) -> None:
    current = datetime(2026, 8, 17, 12, tzinfo=UTC)
    store = ProblemStore(tmp_path / "problems", retention_days=30, max_reports=3,
                         now=lambda: current)
    store.record(_report(when=current - timedelta(days=31), task_id="old"))
    for index in range(5):
        store.record(_report(when=current - timedelta(minutes=index), task_id=f"task-{index}"))
    reports = store.list_reports()
    assert len(reports) == 3
    assert {item.task_id for item in reports} == {"task-0", "task-1", "task-2"}


def test_build_problem_report_hides_windows_actions_on_other_platforms(tmp_path: Path) -> None:
    report = build_problem_report(
        FileNotFoundError(errno.ENOENT, "removed"),
        stage="commit", purpose="patch_binary", temporary_path=tmp_path / "missing.part",
        write_started=True, task_id="patch-1", platform="linux",
    )
    assert report.code is ProblemCode.PATCH_SECURITY_INTERFERENCE_SUSPECTED
    assert ProblemAction.OPEN_MICROSOFT_FALSE_POSITIVE in report.allowed_actions
    assert ProblemAction.OPEN_WINDOWS_SECURITY not in report.allowed_actions


def test_sanitize_technical_details_redacts_query_credentials_and_home(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("USERPROFILE", r"C:\Users\person")
    value = sanitize_technical_details(
        "GET https://example.com/file?token=secret Authorization: Bearer123 "
        r"C:\Users\person\Downloads\file.zip"
    )
    assert "token=secret" not in value
    assert "Bearer123" not in value
    assert "<redacted>" in value
    assert "<user-home>" in value
