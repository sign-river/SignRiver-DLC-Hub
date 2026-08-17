"""客户端与启动器共享的结构化问题记录。"""

from __future__ import annotations

import errno
import hashlib
import json
import os
import re
import socket
import ssl
import tempfile
import traceback
from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4


class ProblemCategory(StrEnum):
    NETWORK = "network"
    FILESYSTEM = "filesystem"
    INTEGRITY = "integrity"
    PATCH = "patch"
    UPDATE = "update"
    APPLICATION = "application"


class ProblemSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class ProblemStatus(StrEnum):
    OPEN = "open"
    RESOLVED = "resolved"


class ProblemAction(StrEnum):
    """可持久化的固定动作标识；这些值不是命令或 URL。"""

    COPY_DETAILS = "copy_details"
    COPY_HASH_INFO = "copy_hash_info"
    OPEN_LOG_DIRECTORY = "open_log_directory"
    OPEN_CACHE_DIRECTORY = "open_cache_directory"
    EXPORT_DIAGNOSTICS = "export_diagnostics"
    RETRY_TASK = "retry_task"
    MARK_RESOLVED = "mark_resolved"
    DELETE = "delete"
    OPEN_WINDOWS_SECURITY = "open_windows_security"
    OPEN_MICROSOFT_FALSE_POSITIVE = "open_microsoft_false_positive"


class ProblemCode(StrEnum):
    NET_TIMEOUT = "NET-TIMEOUT"
    NET_DNS = "NET-DNS"
    NET_TLS = "NET-TLS"
    NET_HTTP = "NET-HTTP"
    NET_CONNECTION = "NET-CONNECTION"
    FS_PERMISSION_DENIED = "FS-PERMISSION-DENIED"
    FS_DISK_FULL = "FS-DISK-FULL"
    FS_INVALID_PATH = "FS-INVALID-PATH"
    FS_FILE_BUSY = "FS-FILE-BUSY"
    FS_READ_ONLY = "FS-READ-ONLY"
    FS_NOT_FOUND = "FS-NOT-FOUND"
    FS_IO = "FS-IO"
    PKG_SIZE_MISMATCH = "PKG-SIZE-MISMATCH"
    PKG_HASH_MISMATCH = "PKG-HASH-MISMATCH"
    PKG_INVALID_FORMAT = "PKG-INVALID-FORMAT"
    PATCH_SECURITY_INTERFERENCE_SUSPECTED = "PATCH-SECURITY-INTERFERENCE-SUSPECTED"
    PATCH_MISSING_HASH = "PATCH-MISSING-HASH"
    PATCH_APPLY_FAILED = "PATCH-APPLY-FAILED"
    PATCH_AUDIT_FAILED = "PATCH-AUDIT-FAILED"
    UPDATE_DOWNLOAD_FAILED = "UPDATE-DOWNLOAD-FAILED"
    UPDATE_APPLY_FAILED = "UPDATE-APPLY-FAILED"
    UPDATE_ROLLED_BACK = "UPDATE-ROLLED-BACK"
    APP_MODULE_LOAD_FAILED = "APP-MODULE-LOAD-FAILED"
    APP_UNEXPECTED = "APP-UNEXPECTED"


@dataclass(frozen=True, slots=True)
class ProblemClassification:
    code: ProblemCode
    category: ProblemCategory
    severity: ProblemSeverity
    summary: str
    suggestion: str
    stop_retry: bool = False


@dataclass(frozen=True, slots=True)
class ProblemReport:
    event_id: str
    code: ProblemCode
    category: ProblemCategory
    severity: ProblemSeverity
    occurred_at: str
    last_occurred_at: str
    stage: str
    summary: str
    suggestion: str
    technical_details: str = ""
    app_version: str | None = None
    launcher_version: str | None = None
    platform: str | None = None
    task_id: str | None = None
    filename: str | None = None
    expected_sha256: str | None = None
    actual_sha256: str | None = None
    status: ProblemStatus = ProblemStatus.OPEN
    retry_count: int = 0
    allowed_actions: tuple[ProblemAction, ...] = ()

    @classmethod
    def create(
        cls,
        *,
        code: ProblemCode | str,
        category: ProblemCategory | str,
        severity: ProblemSeverity | str,
        stage: str,
        summary: str,
        suggestion: str,
        technical_details: str = "",
        app_version: str | None = None,
        launcher_version: str | None = None,
        platform: str | None = None,
        task_id: str | None = None,
        filename: str | None = None,
        expected_sha256: str | None = None,
        actual_sha256: str | None = None,
        allowed_actions: Iterable[ProblemAction | str] = (),
        occurred_at: datetime | None = None,
    ) -> "ProblemReport":
        timestamp = _iso_timestamp(occurred_at or datetime.now(UTC))
        return cls(
            event_id=uuid4().hex,
            code=ProblemCode(code),
            category=ProblemCategory(category),
            severity=ProblemSeverity(severity),
            occurred_at=timestamp,
            last_occurred_at=timestamp,
            stage=_clean(stage, 80),
            summary=_clean(summary, 300),
            suggestion=_clean(suggestion, 1000),
            technical_details=sanitize_technical_details(technical_details),
            app_version=_optional(app_version, 80),
            launcher_version=_optional(launcher_version, 80),
            platform=_optional(platform, 80),
            task_id=_optional(task_id, 160),
            filename=_safe_filename(filename),
            expected_sha256=_safe_hash(expected_sha256),
            actual_sha256=_safe_hash(actual_sha256),
            allowed_actions=_normalize_actions(allowed_actions),
        )

    @property
    def fingerprint(self) -> str:
        value = "\x1f".join((
            self.code.value,
            self.stage,
            self.task_id or "",
            self.filename or "",
            self.expected_sha256 or "",
        ))
        return hashlib.sha256(value.encode()).hexdigest()

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "event_id": self.event_id,
            "code": self.code.value,
            "category": self.category.value,
            "severity": self.severity.value,
            "occurred_at": self.occurred_at,
            "last_occurred_at": self.last_occurred_at,
            "stage": self.stage,
            "summary": self.summary,
            "suggestion": self.suggestion,
            "technical_details": self.technical_details,
            "app_version": self.app_version,
            "launcher_version": self.launcher_version,
            "platform": self.platform,
            "task_id": self.task_id,
            "filename": self.filename,
            "expected_sha256": self.expected_sha256,
            "actual_sha256": self.actual_sha256,
            "status": self.status.value,
            "retry_count": self.retry_count,
            "allowed_actions": [item.value for item in self.allowed_actions],
        }

    @classmethod
    def from_dict(cls, value: object) -> "ProblemReport":
        if not isinstance(value, dict):
            raise ValueError("problem report must be an object")
        event_id = str(value["event_id"])
        if not re.fullmatch(r"[A-Za-z0-9_-]{8,80}", event_id):
            raise ValueError("invalid event ID")
        occurred_at = _validated_timestamp(value["occurred_at"])
        retry_count = int(value.get("retry_count", 0))
        if retry_count < 0:
            raise ValueError("invalid retry count")
        return cls(
            event_id=event_id,
            code=ProblemCode(value["code"]),
            category=ProblemCategory(value["category"]),
            severity=ProblemSeverity(value["severity"]),
            occurred_at=occurred_at,
            last_occurred_at=_validated_timestamp(value.get("last_occurred_at", occurred_at)),
            stage=_clean(str(value["stage"]), 80),
            summary=_clean(str(value["summary"]), 300),
            suggestion=_clean(str(value["suggestion"]), 1000),
            technical_details=sanitize_technical_details(str(value.get("technical_details", ""))),
            app_version=_optional(value.get("app_version"), 80),
            launcher_version=_optional(value.get("launcher_version"), 80),
            platform=_optional(value.get("platform"), 80),
            task_id=_optional(value.get("task_id"), 160),
            filename=_safe_filename(value.get("filename")),
            expected_sha256=_safe_hash(value.get("expected_sha256")),
            actual_sha256=_safe_hash(value.get("actual_sha256")),
            status=ProblemStatus(value.get("status", ProblemStatus.OPEN.value)),
            retry_count=retry_count,
            allowed_actions=_normalize_actions(value.get("allowed_actions", ())),
        )

    def format_details(self) -> str:
        lines = [
            f"事件 ID：{self.event_id}", f"错误码：{self.code.value}",
            f"类别：{self.category.value}", f"严重程度：{self.severity.value}",
            f"状态：{self.status.value}", f"时间：{self.last_occurred_at}",
            f"阶段：{self.stage}", f"摘要：{self.summary}", f"建议：{self.suggestion}",
        ]
        for label, value in (
            ("程序版本", self.app_version), ("启动器版本", self.launcher_version),
            ("平台", self.platform), ("任务 ID", self.task_id), ("文件名", self.filename),
            ("预期 SHA-256", self.expected_sha256), ("实际 SHA-256", self.actual_sha256),
        ):
            if value:
                lines.append(f"{label}：{value}")
        if self.retry_count:
            lines.append(f"重复次数：{self.retry_count}")
        if self.technical_details:
            lines.extend(("技术详情：", self.technical_details))
        return "\n".join(lines)


class ProblemStore:
    def __init__(
        self,
        directory: Path | str,
        *,
        retention_days: int = 30,
        max_reports: int = 100,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if retention_days < 1 or max_reports < 1:
            raise ValueError("retention limits must be positive")
        self.directory = Path(directory)
        self.retention_days = retention_days
        self.max_reports = max_reports
        self._now = now or (lambda: datetime.now(UTC))
        self.directory.mkdir(parents=True, exist_ok=True)
        self.prune()

    def record(self, report: ProblemReport) -> ProblemReport:
        duplicate = next((item for item in self.list_reports(include_resolved=False)
                          if item.fingerprint == report.fingerprint), None)
        if duplicate:
            report = replace(
                duplicate,
                last_occurred_at=report.last_occurred_at,
                severity=report.severity,
                summary=report.summary,
                suggestion=report.suggestion,
                technical_details=report.technical_details,
                actual_sha256=report.actual_sha256,
                retry_count=duplicate.retry_count + 1,
                allowed_actions=report.allowed_actions,
            )
        self._write(report)
        self.prune()
        return report

    def list_reports(self, *, include_resolved: bool = True) -> list[ProblemReport]:
        reports: list[ProblemReport] = []
        for item in self.directory.glob("*.json"):
            try:
                report = ProblemReport.from_dict(json.loads(item.read_text(encoding="utf-8")))
            except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError, ValueError):
                continue
            if include_resolved or report.status is ProblemStatus.OPEN:
                reports.append(report)
        return sorted(reports, key=lambda item: _parse_timestamp(item.last_occurred_at), reverse=True)

    def unresolved_count(self) -> int:
        return len(self.list_reports(include_resolved=False))

    def get(self, event_id: str) -> ProblemReport | None:
        if not re.fullmatch(r"[A-Za-z0-9_-]{8,80}", event_id):
            return None
        try:
            return ProblemReport.from_dict(json.loads(
                (self.directory / f"{event_id}.json").read_text(encoding="utf-8")
            ))
        except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError, ValueError):
            return None

    def mark_resolved(self, event_id: str) -> ProblemReport | None:
        report = self.get(event_id)
        if report is None:
            return None
        report = replace(report, status=ProblemStatus.RESOLVED,
                         last_occurred_at=_iso_timestamp(self._now()))
        self._write(report)
        return report

    def resolve_matching(self, *, code: ProblemCode | str | None = None,
                         task_id: str | None = None, filename: str | None = None) -> int:
        expected_code = ProblemCode(code) if code else None
        matches = [item for item in self.list_reports(include_resolved=False)
                   if (expected_code is None or item.code is expected_code)
                   and (task_id is None or item.task_id == task_id)
                   and (filename is None or item.filename == filename)]
        for item in matches:
            self.mark_resolved(item.event_id)
        return len(matches)

    def delete(self, event_id: str) -> bool:
        if not re.fullmatch(r"[A-Za-z0-9_-]{8,80}", event_id):
            return False
        try:
            (self.directory / f"{event_id}.json").unlink()
        except FileNotFoundError:
            return False
        return True

    def clear(self) -> None:
        for item in self.directory.glob("*.json"):
            item.unlink(missing_ok=True)

    def prune(self) -> None:
        cutoff = self._now().astimezone(UTC) - timedelta(days=self.retention_days)
        recent = [item for item in self.list_reports()
                  if _parse_timestamp(item.last_occurred_at) >= cutoff]
        keep = {item.event_id for item in recent[:self.max_reports]}
        for item in self.directory.glob("*.json"):
            if item.stem not in keep:
                item.unlink(missing_ok=True)

    def _write(self, report: ProblemReport) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        target = self.directory / f"{report.event_id}.json"
        payload = json.dumps(report.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        descriptor, name = tempfile.mkstemp(prefix=f".{report.event_id}.", suffix=".tmp",
                                             dir=self.directory)
        temporary = Path(name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)


def classify_exception(error: BaseException, *, stage: str, purpose: str = "",
                       temporary_path: Path | str | None = None,
                       write_started: bool = False) -> ProblemClassification:
    detail = _exception_chain_text(error).casefold()
    stage = stage.casefold().strip()
    error_number = getattr(error, "errno", None)
    missing = temporary_path is not None and not Path(temporary_path).exists()
    patch = purpose in {"patch_binary", "patch_metadata"}
    if patch and stage in {"write", "flush", "verify", "commit"} and (
        (write_started and isinstance(error, FileNotFoundError))
        or (error_number in {errno.EACCES, errno.EPERM, errno.EINVAL} and missing)
    ):
        return ProblemClassification(
            ProblemCode.PATCH_SECURITY_INTERFERENCE_SUSPECTED, ProblemCategory.PATCH,
            ProblemSeverity.CRITICAL, "补丁文件写入后不可用，疑似被安全软件拦截",
            "请核对来源与 SHA-256，在系统安全软件中查看本次检测记录，处理后重新下载并验证。",
            stop_retry=True,
        )
    if isinstance(error, TimeoutError) or "timed out" in detail or "timeout" in detail:
        return _network(ProblemCode.NET_TIMEOUT, "连接超时", "请检查网络连接后重试。")
    if isinstance(error, socket.gaierror) or "getaddrinfo failed" in detail or "name or service not known" in detail:
        return _network(ProblemCode.NET_DNS, "无法解析下载域名", "请检查 DNS 或切换网络后重试。")
    if isinstance(error, (ssl.SSLError, ssl.CertificateError)) or "certificate verify failed" in detail or "tls" in detail:
        return _network(ProblemCode.NET_TLS, "安全连接校验失败", "请检查系统时间、证书和网络代理后重试。")
    if isinstance(error, HTTPError) or re.search(r"\bhttp(?: error)?\s*[45]\d\d\b", detail):
        return _network(ProblemCode.NET_HTTP, "下载服务器返回错误", "请稍后重试；持续失败时导出诊断信息。")
    if isinstance(error, URLError) or any(word in detail for word in (
        "connection refused", "connection reset", "remote end closed", "network is unreachable"
    )):
        return _network(ProblemCode.NET_CONNECTION, "网络连接中断", "请检查网络连接后重试。")
    if any(word in detail for word in ("sha-256", "sha256", "hash mismatch", "哈希")):
        return ProblemClassification(ProblemCode.PKG_HASH_MISMATCH, ProblemCategory.INTEGRITY,
                                     ProblemSeverity.ERROR, "下载文件的 SHA-256 与目录记录不一致",
                                     "请删除缓存并重新下载；持续失败时切换下载源。")
    if any(word in detail for word in ("size mismatch", "大小不匹配", "unexpected download size")):
        return ProblemClassification(ProblemCode.PKG_SIZE_MISMATCH, ProblemCategory.INTEGRITY,
                                     ProblemSeverity.ERROR, "下载文件大小与目录记录不一致",
                                     "请删除缓存并重新下载。")
    if (
        any(word in detail for word in ("invalid archive", "bad zip", "包格式", "invalid package"))
        or (stage == "verify" and isinstance(error, ValueError))
    ):
        return ProblemClassification(ProblemCode.PKG_INVALID_FORMAT, ProblemCategory.INTEGRITY,
                                     ProblemSeverity.ERROR, "下载包格式无效或已损坏",
                                     "请重新下载并验证文件完整性。")
    if isinstance(error, OSError):
        if error_number in {errno.EACCES, errno.EPERM}:
            return _filesystem(ProblemCode.FS_PERMISSION_DENIED, "没有权限写入文件", "请关闭占用程序并检查目录权限后重试。")
        if error_number == errno.ENOSPC:
            return _filesystem(ProblemCode.FS_DISK_FULL, "磁盘可用空间不足", "请释放磁盘空间后重试。")
        if error_number in {errno.EINVAL, errno.ENAMETOOLONG}:
            return _filesystem(ProblemCode.FS_INVALID_PATH, "文件路径无效", "请缩短路径或更换缓存目录后重试。")
        if error_number in {errno.EBUSY, errno.ETXTBSY} or "being used by another process" in detail:
            return _filesystem(ProblemCode.FS_FILE_BUSY, "文件正被其他程序占用", "请关闭占用该文件的程序后重试。")
        if error_number == errno.EROFS:
            return _filesystem(ProblemCode.FS_READ_ONLY, "目标文件系统为只读", "请选择可写目录后重试。")
        if isinstance(error, FileNotFoundError):
            return _filesystem(ProblemCode.FS_NOT_FOUND, "所需文件不存在", "请重新下载或刷新目录后重试。")
        return _filesystem(ProblemCode.FS_IO, "本地文件读写失败", "请检查目录权限、磁盘空间和文件占用情况。")
    return ProblemClassification(ProblemCode.APP_UNEXPECTED, ProblemCategory.APPLICATION,
                                 ProblemSeverity.ERROR, "程序遇到未预期错误",
                                 "请重试；持续失败时导出诊断信息。")


def build_problem_report(error: BaseException, *, stage: str, purpose: str = "",
                         temporary_path: Path | str | None = None,
                         write_started: bool = False, **context: object) -> ProblemReport:
    result = classify_exception(error, stage=stage, purpose=purpose,
                                temporary_path=temporary_path, write_started=write_started)
    actions = [ProblemAction.COPY_DETAILS, ProblemAction.OPEN_LOG_DIRECTORY,
               ProblemAction.EXPORT_DIAGNOSTICS, ProblemAction.MARK_RESOLVED, ProblemAction.DELETE]
    if context.get("task_id"):
        actions.append(ProblemAction.RETRY_TASK)
    if temporary_path is not None:
        actions.append(ProblemAction.OPEN_CACHE_DIRECTORY)
    if result.code is ProblemCode.PATCH_SECURITY_INTERFERENCE_SUSPECTED:
        actions.extend((ProblemAction.COPY_HASH_INFO, ProblemAction.OPEN_MICROSOFT_FALSE_POSITIVE))
        if str(context.get("platform", "")).casefold().startswith("win"):
            actions.append(ProblemAction.OPEN_WINDOWS_SECURITY)
    return ProblemReport.create(
        code=result.code, category=result.category, severity=result.severity,
        stage=stage, summary=result.summary, suggestion=result.suggestion,
        technical_details=_exception_chain_text(error),
        app_version=context.get("app_version"), launcher_version=context.get("launcher_version"),
        platform=context.get("platform"), task_id=context.get("task_id"),
        filename=context.get("filename"), expected_sha256=context.get("expected_sha256"),
        actual_sha256=context.get("actual_sha256"), allowed_actions=actions,
    )


def sanitize_technical_details(value: str, *, max_length: int = 12000) -> str:
    text = _redact_url_queries(str(value).replace("\x00", ""))
    text = re.sub(
        r"(?i)\b(authorization|cookie|set-cookie|password|passwd|token|secret|api[_-]?key)\b\s*[:=]\s*([^\s;,]+)",
        r"\1=<redacted>", text,
    )
    homes = {str(Path.home()), os.environ.get("USERPROFILE", ""), os.environ.get("HOME", "")}
    for home in sorted(filter(None, homes), key=len, reverse=True):
        text = re.sub(re.escape(home), "<user-home>", text, flags=re.IGNORECASE)
    return text[:max_length]


def _exception_chain_text(error: BaseException) -> str:
    return "".join(traceback.format_exception(type(error), error, error.__traceback__)).strip()


def _redact_url_queries(text: str) -> str:
    pattern = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
    def redact(match: re.Match[str]) -> str:
        raw = match.group(0)
        trailing = ""
        while raw and raw[-1] in ").,;]}":
            trailing = raw[-1] + trailing
            raw = raw[:-1]
        try:
            parsed = urlsplit(raw)
            host = parsed.hostname or ""
            if parsed.port:
                host = f"{host}:{parsed.port}"
            safe = urlunsplit((parsed.scheme, host, parsed.path,
                               "<redacted>" if parsed.query else "", ""))
            return safe + trailing
        except ValueError:
            return "<redacted-url>" + trailing
    return pattern.sub(redact, text)


def _normalize_actions(values: Iterable[ProblemAction | str]) -> tuple[ProblemAction, ...]:
    actions: list[ProblemAction] = []
    for value in values:
        try:
            action = ProblemAction(value)
        except (TypeError, ValueError):
            continue
        if action not in actions:
            actions.append(action)
    return tuple(actions)


def _safe_hash(value: object) -> str | None:
    if value in (None, ""):
        return None
    value = str(value).strip().lower()
    return value if re.fullmatch(r"[0-9a-f]{64}", value) else None


def _safe_filename(value: object) -> str | None:
    return None if value in (None, "") else _clean(Path(str(value)).name, 260)


def _optional(value: object, limit: int) -> str | None:
    return None if value in (None, "") else _clean(str(value), limit)


def _clean(value: str, limit: int) -> str:
    return str(value).replace("\x00", "").strip()[:limit]


def _iso_timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _validated_timestamp(value: object) -> str:
    return _iso_timestamp(_parse_timestamp(str(value)))


def _parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _network(code: ProblemCode, summary: str, suggestion: str) -> ProblemClassification:
    return ProblemClassification(code, ProblemCategory.NETWORK, ProblemSeverity.ERROR, summary, suggestion)


def _filesystem(code: ProblemCode, summary: str, suggestion: str) -> ProblemClassification:
    return ProblemClassification(code, ProblemCategory.FILESYSTEM, ProblemSeverity.ERROR, summary, suggestion)


__all__ = [
    "ProblemAction", "ProblemCategory", "ProblemClassification", "ProblemCode",
    "ProblemReport", "ProblemSeverity", "ProblemStatus", "ProblemStore",
    "build_problem_report", "classify_exception", "sanitize_technical_details",
]
