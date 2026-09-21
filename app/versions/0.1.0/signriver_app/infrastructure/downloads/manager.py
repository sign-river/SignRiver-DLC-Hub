"""Synchronous download engine designed to run on a worker thread."""

from __future__ import annotations

import hashlib
import os
import re
import threading
import time
from contextlib import closing
from dataclasses import dataclass, replace
from pathlib import Path
from typing import BinaryIO, Callable
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from signriver_common.problems import ProblemCategory, classify_exception

from ...domain import (
    DownloadSnapshot,
    DownloadSpec,
    DownloadStage,
    DownloadState,
)
from ..net_errors import describe_network_error

_SAFE_FILENAME = re.compile(r"^[^\\/:*?\"<>|\x00-\x1f]+$")


@dataclass(frozen=True, slots=True)
class DownloadPolicy:
    attempts: int = 3
    # 取消/暂停只在每个分块之间检查，分块越大，点击取消后的响应越慢；
    # 慢速网络下一块 256 KiB 可能要好几秒，这里降到 32 KiB。
    chunk_size: int = 32 * 1024
    timeout: float | None = 30
    retry_delay: float = 0.5
    max_bytes_per_second: int | None = None

    def __post_init__(self) -> None:
        if (
            self.attempts < 1
            or self.chunk_size < 1
            or (self.timeout is not None and self.timeout <= 0)
            or self.retry_delay < 0
        ):
            raise ValueError("invalid download policy")
        if self.max_bytes_per_second is not None and self.max_bytes_per_second < 1:
            raise ValueError("max_bytes_per_second must be positive")


class DownloadControl:
    def __init__(self) -> None:
        self._pause = threading.Event()
        self._cancel = threading.Event()

    def pause(self) -> None:
        self._pause.set()

    def cancel(self) -> None:
        self._cancel.set()

    @property
    def pause_requested(self) -> bool:
        return self._pause.is_set()

    @property
    def cancel_requested(self) -> bool:
        return self._cancel.is_set()


class DownloadManager:
    def __init__(
        self,
        cache_root: Path,
        *,
        policy: DownloadPolicy | None = None,
        opener: Callable[[str, float | None], BinaryIO] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.cache_root = Path(cache_root)
        self.policy = policy or DownloadPolicy()
        self._opener = opener or self._open_https
        self._sleep = sleep
        self._clock = clock

    def configure_timeout(self, timeout: float | None) -> None:
        """Apply a timeout to future connections without replacing the queue."""
        self.policy = replace(self.policy, timeout=timeout)

    def run(
        self,
        spec: DownloadSpec,
        control: DownloadControl | None = None,
        on_change: Callable[[DownloadSnapshot], None] | None = None,
        verifier: Callable[[Path, str], object] | None = None,
    ) -> DownloadSnapshot:
        self._validate_spec(spec)
        control = control or DownloadControl()
        notify = on_change or (lambda _snapshot: None)
        stage = DownloadStage.PREPARE
        downloads = self.cache_root / "downloads"
        packages = self.cache_root / "packages"
        quarantine = self.cache_root / "quarantine"
        for directory in (downloads, packages, quarantine):
            directory.mkdir(parents=True, exist_ok=True)
        part = downloads / spec.game_id / f"{spec.task_id}.part"
        part.parent.mkdir(parents=True, exist_ok=True)
        snapshot = DownloadSnapshot(spec=spec, total_bytes=spec.expected_size)
        notify(snapshot)

        # GitLink's current attachment endpoint ignores Range. A paused partial
        # file therefore cannot be appended safely and is restarted on resume.
        if part.exists():
            part.unlink()

        for attempt in range(1, self.policy.attempts + 1):
            if control.cancel_requested:
                part.unlink(missing_ok=True)
                return self._emit(snapshot.evolve(
                    state=DownloadState.CANCELLED, attempt=attempt, error=None,
                    failure_code=None, failure_stage=None,
                    speed_bytes_per_second=None, eta_seconds=None,
                ), notify)
            if control.pause_requested:
                return self._emit(snapshot.evolve(
                    state=DownloadState.PAUSED, attempt=attempt, error=None,
                    failure_code=None, failure_stage=None,
                    speed_bytes_per_second=None, eta_seconds=None,
                ), notify)
            snapshot = self._emit(snapshot.evolve(
                state=DownloadState.DOWNLOADING,
                attempt=attempt,
                bytes_downloaded=0,
                error=None,
                failure_code=None,
                failure_stage=None,
                speed_bytes_per_second=None,
                eta_seconds=None,
            ), notify)
            digest = hashlib.sha256()
            downloaded = 0
            cancelled = False
            paused = False
            write_started = False
            started_at = self._clock()
            active_url = ""
            try:
                stage = DownloadStage.WRITE
                with part.open("wb") as output:
                    for part_url in spec.urls:
                        active_url = part_url
                        stage = DownloadStage.CONNECT
                        with closing(self._opener(part_url, self.policy.timeout)) as response:
                            while True:
                                if control.cancel_requested:
                                    cancelled = True
                                    break
                                if control.pause_requested:
                                    paused = True
                                    break
                                stage = DownloadStage.READ
                                block = response.read(self.policy.chunk_size)
                                if not block:
                                    break
                                stage = DownloadStage.WRITE
                                output.write(block)
                                write_started = True
                                digest.update(block)
                                downloaded += len(block)
                                elapsed = max(self._clock() - started_at, 0.000001)
                                speed = downloaded / elapsed
                                total = spec.expected_size
                                eta = ((total - downloaded) / speed) if total and speed > 0 else None
                                snapshot = self._emit(snapshot.evolve(
                                    bytes_downloaded=downloaded,
                                    speed_bytes_per_second=speed,
                                    eta_seconds=max(eta, 0) if eta is not None else None,
                                ), notify)
                                if self.policy.max_bytes_per_second:
                                    expected_elapsed = downloaded / self.policy.max_bytes_per_second
                                    remaining_delay = expected_elapsed - (self._clock() - started_at)
                                    if remaining_delay > 0:
                                        self._sleep(remaining_delay)
                        if cancelled or paused:
                            break
                    if not cancelled and not paused:
                        stage = DownloadStage.FLUSH
                        output.flush()
                        os.fsync(output.fileno())
                if cancelled:
                    part.unlink(missing_ok=True)
                    return self._emit(snapshot.evolve(
                        state=DownloadState.CANCELLED,
                        bytes_downloaded=downloaded,
                        error=None,
                        failure_code=None,
                        failure_stage=None,
                        speed_bytes_per_second=None,
                        eta_seconds=None,
                    ), notify)
                if paused:
                    # GitLink does not support a reliable Range resume. Close the
                    # file first, discard the half package, and restart it later.
                    part.unlink(missing_ok=True)
                    return self._emit(snapshot.evolve(
                        state=DownloadState.PAUSED,
                        bytes_downloaded=0,
                        error=None,
                        failure_code=None,
                        failure_stage=None,
                        speed_bytes_per_second=None,
                        eta_seconds=None,
                    ), notify)
                requested = self._finish_requested_control(
                    control=control,
                    part=part,
                    snapshot=snapshot,
                    downloaded=downloaded,
                    attempt=attempt,
                    callback=notify,
                )
                if requested is not None:
                    return requested
                stage = DownloadStage.VERIFY
                if not part.is_file():
                    raise FileNotFoundError(part)
                actual_hash = digest.hexdigest()
                snapshot = self._emit(snapshot.evolve(
                    state=DownloadState.VERIFYING,
                    bytes_downloaded=downloaded,
                    sha256=actual_hash,
                ), notify)
                if spec.expected_size is not None and downloaded != spec.expected_size:
                    raise ValueError(
                        f"size mismatch: expected {spec.expected_size}, got {downloaded}"
                    )
                if (
                    spec.expected_sha256
                    and actual_hash.casefold() != spec.expected_sha256.casefold()
                ):
                    raise ValueError("SHA-256 mismatch")
                requested = self._finish_requested_control(
                    control=control,
                    part=part,
                    snapshot=snapshot,
                    downloaded=downloaded,
                    attempt=attempt,
                    callback=notify,
                )
                if requested is not None:
                    return requested
                if verifier is not None:
                    verifier(part, actual_hash)
                requested = self._finish_requested_control(
                    control=control,
                    part=part,
                    snapshot=snapshot,
                    downloaded=downloaded,
                    attempt=attempt,
                    callback=notify,
                )
                if requested is not None:
                    return requested
                stage = DownloadStage.COMMIT
                target_dir = packages / spec.game_id / actual_hash
                target_dir.mkdir(parents=True, exist_ok=True)
                target = target_dir / spec.filename
                requested = self._finish_requested_control(
                    control=control,
                    part=part,
                    snapshot=snapshot,
                    downloaded=downloaded,
                    attempt=attempt,
                    callback=notify,
                )
                if requested is not None:
                    return requested
                os.replace(part, target)
                return self._emit(snapshot.evolve(
                    state=DownloadState.READY,
                    result_path=target,
                    error=None,
                    failure_code=None,
                    failure_stage=None,
                ), notify)
            except (OSError, TimeoutError, ValueError) as error:
                requested = self._finish_requested_control(
                    control=control,
                    part=part,
                    snapshot=snapshot,
                    downloaded=downloaded,
                    attempt=attempt,
                    callback=notify,
                )
                if requested is not None:
                    return requested
                classification = classify_exception(
                    error,
                    stage=stage.value,
                    purpose=spec.purpose.value,
                    temporary_path=part,
                    write_started=write_started,
                )
                code = classification.code.value
                message = self._describe_failure(
                    error,
                    classification.category,
                    classification.summary,
                    classification.suggestion,
                    active_url=active_url,
                    retrying=(
                        attempt < self.policy.attempts
                        and not classification.stop_retry
                        and classification.category
                        in {ProblemCategory.NETWORK, ProblemCategory.INTEGRITY}
                    ),
                )
                should_retry = (
                    attempt < self.policy.attempts
                    and not classification.stop_retry
                    and classification.category
                    in {ProblemCategory.NETWORK, ProblemCategory.INTEGRITY}
                )
                if classification.category is ProblemCategory.INTEGRITY:
                    isolated = quarantine / spec.game_id / f"{spec.task_id}-latest.bad"
                    isolated.parent.mkdir(parents=True, exist_ok=True)
                    if part.exists():
                        os.replace(part, isolated)
                else:
                    part.unlink(missing_ok=True)
                if should_retry:
                    snapshot = self._emit(snapshot.evolve(
                        state=DownloadState.RETRYING,
                        bytes_downloaded=0 if classification.category is ProblemCategory.INTEGRITY else downloaded,
                        error=message,
                        failure_code=code,
                        failure_stage=stage,
                        speed_bytes_per_second=None,
                        eta_seconds=None,
                    ), notify)
                    self._sleep(self.policy.retry_delay * attempt)
                    continue
                terminal_state = (
                    DownloadState.CORRUPT
                    if classification.category is ProblemCategory.INTEGRITY
                    else DownloadState.FAILED
                )
                return self._emit(snapshot.evolve(
                    state=terminal_state,
                    bytes_downloaded=downloaded,
                    error=message,
                    failure_code=code,
                    failure_stage=stage,
                    speed_bytes_per_second=None,
                    eta_seconds=None,
                ), notify)
        raise AssertionError("unreachable")

    @staticmethod
    def _describe_failure(
        error: BaseException,
        category: ProblemCategory,
        summary: str,
        suggestion: str,
        *,
        active_url: str,
        retrying: bool,
    ) -> str:
        if category is ProblemCategory.NETWORK:
            action = "下载资源，准备重试" if retrying else "下载资源"
            return describe_network_error(error, url=active_url, action=action)
        if category is ProblemCategory.INTEGRITY:
            if retrying:
                return f"包校验失败，准备重新下载：{error}"
            return str(error)
        return f"{summary}：{suggestion}"

    @classmethod
    def _finish_requested_control(
        cls,
        *,
        control: DownloadControl,
        part: Path,
        snapshot: DownloadSnapshot,
        downloaded: int,
        attempt: int,
        callback: Callable[[DownloadSnapshot], None],
    ) -> DownloadSnapshot | None:
        """Finish a late pause/cancel before a verified package is committed."""
        if control.cancel_requested:
            part.unlink(missing_ok=True)
            return cls._emit(snapshot.evolve(
                state=DownloadState.CANCELLED,
                attempt=attempt,
                bytes_downloaded=downloaded,
                error=None,
                speed_bytes_per_second=None,
                eta_seconds=None,
            ), callback)
        if control.pause_requested:
            part.unlink(missing_ok=True)
            return cls._emit(snapshot.evolve(
                state=DownloadState.PAUSED,
                attempt=attempt,
                bytes_downloaded=0,
                error=None,
                speed_bytes_per_second=None,
                eta_seconds=None,
            ), callback)
        return None

    @staticmethod
    def _emit(snapshot: DownloadSnapshot, callback: Callable[[DownloadSnapshot], None]) -> DownloadSnapshot:
        callback(snapshot)
        return snapshot

    @staticmethod
    def _validate_spec(spec: DownloadSpec) -> None:
        for url in spec.urls:
            parsed = urlparse(url)
            if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
                raise ValueError("download URL must be credential-free HTTPS")
        if not _SAFE_FILENAME.fullmatch(spec.filename) or spec.filename in {".", ".."}:
            raise ValueError("unsafe download filename")
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", spec.game_id):
            raise ValueError("unsafe game ID")
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", spec.task_id):
            raise ValueError("unsafe download task ID")
        if spec.expected_size is not None and spec.expected_size < 0:
            raise ValueError("expected size cannot be negative")
        if spec.expected_sha256 is not None and not re.fullmatch(r"[0-9a-fA-F]{64}", spec.expected_sha256):
            raise ValueError("expected SHA-256 is invalid")

    @staticmethod
    def _open_https(url: str, timeout: float | None) -> BinaryIO:
        request = Request(url, headers={"Accept": "application/octet-stream", "User-Agent": "SignRiver-DLC-Hub/0.1"})
        response = urlopen(request, timeout=timeout)
        final = urlparse(response.geturl())
        if final.scheme != "https":
            response.close()
            raise OSError("download redirected to a non-HTTPS endpoint")
        return response
