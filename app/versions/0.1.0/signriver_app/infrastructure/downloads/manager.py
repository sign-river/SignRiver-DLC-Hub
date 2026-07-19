"""Synchronous download engine designed to run on a worker thread."""

from __future__ import annotations

import hashlib
import os
import re
import threading
import time
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Callable
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from ...domain import DownloadSnapshot, DownloadSpec, DownloadState

_SAFE_FILENAME = re.compile(r"^[^\\/:*?\"<>|\x00-\x1f]+$")


@dataclass(frozen=True, slots=True)
class DownloadPolicy:
    attempts: int = 3
    chunk_size: int = 256 * 1024
    timeout: float = 30
    retry_delay: float = 0.5
    max_bytes_per_second: int | None = None

    def __post_init__(self) -> None:
        if self.attempts < 1 or self.chunk_size < 1 or self.timeout <= 0 or self.retry_delay < 0:
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
        opener: Callable[[str, float], BinaryIO] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.cache_root = Path(cache_root)
        self.policy = policy or DownloadPolicy()
        self._opener = opener or self._open_https
        self._sleep = sleep
        self._clock = clock

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
        downloads = self.cache_root / "downloads"
        packages = self.cache_root / "packages"
        quarantine = self.cache_root / "quarantine"
        for directory in (downloads, packages, quarantine):
            directory.mkdir(parents=True, exist_ok=True)
        part = downloads / f"{spec.task_id}.part"
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
                    speed_bytes_per_second=None, eta_seconds=None,
                ), notify)
            if control.pause_requested:
                return self._emit(snapshot.evolve(
                    state=DownloadState.PAUSED, attempt=attempt, error=None,
                    speed_bytes_per_second=None, eta_seconds=None,
                ), notify)
            snapshot = self._emit(snapshot.evolve(
                state=DownloadState.DOWNLOADING,
                attempt=attempt,
                bytes_downloaded=0,
                error=None,
                speed_bytes_per_second=None,
                eta_seconds=None,
            ), notify)
            digest = hashlib.sha256()
            downloaded = 0
            cancelled = False
            paused = False
            started_at = self._clock()
            try:
                with part.open("wb") as output:
                    for part_url in spec.urls:
                        with closing(self._opener(part_url, self.policy.timeout)) as response:
                            while True:
                                if control.cancel_requested:
                                    cancelled = True
                                    break
                                if control.pause_requested:
                                    paused = True
                                    break
                                block = response.read(self.policy.chunk_size)
                                if not block:
                                    break
                                output.write(block)
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
                        output.flush()
                        os.fsync(output.fileno())
                if cancelled:
                    part.unlink(missing_ok=True)
                    return self._emit(snapshot.evolve(
                        state=DownloadState.CANCELLED,
                        bytes_downloaded=downloaded,
                        error=None,
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
                actual_hash = digest.hexdigest()
                snapshot = self._emit(snapshot.evolve(state=DownloadState.VERIFYING, bytes_downloaded=downloaded, sha256=actual_hash), notify)
                if spec.expected_size is not None and downloaded != spec.expected_size:
                    raise ValueError(f"size mismatch: expected {spec.expected_size}, got {downloaded}")
                if spec.expected_sha256 and actual_hash.casefold() != spec.expected_sha256.casefold():
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
                target_dir = packages / actual_hash
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
                return self._emit(snapshot.evolve(state=DownloadState.READY, result_path=target), notify)
            except ValueError as error:
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
                # Keep only the newest rejected attempt for a task.  Retrying
                # a multi-gigabyte package must not multiply cache usage.
                isolated = quarantine / f"{spec.task_id}-latest.bad"
                if part.exists():
                    os.replace(part, isolated)
                if attempt < self.policy.attempts:
                    snapshot = self._emit(snapshot.evolve(
                        state=DownloadState.RETRYING,
                        bytes_downloaded=0,
                        error=f"包校验失败，准备重新下载：{error}",
                        speed_bytes_per_second=None,
                        eta_seconds=None,
                    ), notify)
                    self._sleep(self.policy.retry_delay * attempt)
                    continue
                return self._emit(snapshot.evolve(state=DownloadState.CORRUPT, bytes_downloaded=downloaded, error=str(error)), notify)
            except (OSError, TimeoutError) as error:
                part.unlink(missing_ok=True)
                if control.cancel_requested:
                    return self._emit(snapshot.evolve(
                        state=DownloadState.CANCELLED,
                        bytes_downloaded=0,
                        error=None,
                        speed_bytes_per_second=None,
                        eta_seconds=None,
                    ), notify)
                if control.pause_requested:
                    return self._emit(snapshot.evolve(
                        state=DownloadState.PAUSED,
                        bytes_downloaded=0,
                        error=None,
                        speed_bytes_per_second=None,
                        eta_seconds=None,
                    ), notify)
                if attempt == self.policy.attempts:
                    return self._emit(snapshot.evolve(state=DownloadState.FAILED, bytes_downloaded=downloaded, error=str(error)), notify)
                snapshot = self._emit(snapshot.evolve(state=DownloadState.RETRYING, bytes_downloaded=downloaded, error=str(error)), notify)
                self._sleep(self.policy.retry_delay * attempt)
        raise AssertionError("unreachable")

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
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", spec.task_id):
            raise ValueError("unsafe download task ID")
        if spec.expected_size is not None and spec.expected_size < 0:
            raise ValueError("expected size cannot be negative")
        if spec.expected_sha256 is not None and not re.fullmatch(r"[0-9a-fA-F]{64}", spec.expected_sha256):
            raise ValueError("expected SHA-256 is invalid")

    @staticmethod
    def _open_https(url: str, timeout: float) -> BinaryIO:
        request = Request(url, headers={"Accept": "application/octet-stream", "User-Agent": "SignRiver-DLC-Hub/0.1"})
        response = urlopen(request, timeout=timeout)
        final = urlparse(response.geturl())
        if final.scheme != "https":
            response.close()
            raise OSError("download redirected to a non-HTTPS endpoint")
        return response
