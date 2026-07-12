"""Threaded download queue coordinating controls, persistence and events."""

from __future__ import annotations

import threading
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Callable

from ..domain import DownloadSnapshot, DownloadSpec, DownloadState
from ..infrastructure.downloads import DownloadControl, DownloadManager


class DownloadQueue:
    def __init__(
        self,
        manager: DownloadManager,
        *,
        repository=None,
        max_concurrent: int = 2,
        on_change: Callable[[DownloadSnapshot], None] | None = None,
        verifier_for: Callable[[DownloadSpec], Callable[[Path], object] | None] | None = None,
    ) -> None:
        if max_concurrent < 1:
            raise ValueError("max_concurrent must be positive")
        self.manager = manager
        self.repository = repository
        self.on_change = on_change or (lambda _snapshot: None)
        self.verifier_for = verifier_for or (lambda _spec: None)
        self._executor = ThreadPoolExecutor(max_workers=max_concurrent, thread_name_prefix="dlc-download")
        self._lock = threading.RLock()
        self._snapshots: dict[str, DownloadSnapshot] = {}
        self._controls: dict[str, DownloadControl] = {}
        self._futures: dict[str, Future] = {}

    def restore(self) -> tuple[DownloadSnapshot, ...]:
        if self.repository is None:
            return ()
        restored = []
        active = {
            DownloadState.QUEUED, DownloadState.DOWNLOADING,
            DownloadState.PAUSING, DownloadState.RETRYING,
            DownloadState.VERIFYING,
        }
        for snapshot in self.repository.recoverable():
            if snapshot.state in active:
                snapshot = snapshot.evolve(
                    state=DownloadState.PAUSED,
                    error="程序上次退出时任务未完成；请手动继续",
                    speed_bytes_per_second=None,
                    eta_seconds=None,
                )
                self.repository.save(snapshot)
            self._snapshots[snapshot.spec.task_id] = snapshot
            restored.append(snapshot)
        return tuple(restored)

    def enqueue(self, spec: DownloadSpec) -> Future:
        with self._lock:
            current = self._futures.get(spec.task_id)
            if current is not None and not current.done():
                raise ValueError(f"download task is already active: {spec.task_id}")
            control = DownloadControl()
            self._controls[spec.task_id] = control
            queued = DownloadSnapshot(spec=spec)
            self._record(queued)
            future = self._executor.submit(self._run, spec, control)
            self._futures[spec.task_id] = future
            return future

    def resume(self, task_id: str) -> Future:
        with self._lock:
            snapshot = self._require(task_id)
            if snapshot.state not in {DownloadState.PAUSED, DownloadState.FAILED}:
                raise ValueError(f"task cannot be resumed from {snapshot.state}")
            return self.enqueue(snapshot.spec)

    def pause(self, task_id: str) -> None:
        with self._lock:
            self._require(task_id)
            control = self._controls.get(task_id)
            if control is None:
                raise ValueError("download task is not active")
            control.pause()

    def cancel(self, task_id: str) -> None:
        with self._lock:
            snapshot = self._require(task_id)
            control = self._controls.get(task_id)
            if control is not None:
                control.cancel()
            elif snapshot.state is DownloadState.PAUSED:
                self._record(snapshot.evolve(state=DownloadState.CANCELLED, error=None))
            else:
                raise ValueError("download task is not cancellable")

    def snapshots(self) -> tuple[DownloadSnapshot, ...]:
        with self._lock:
            return tuple(self._snapshots.values())

    def shutdown(self, *, wait: bool = False) -> None:
        with self._lock:
            for control in self._controls.values():
                control.pause()
        self._executor.shutdown(wait=wait, cancel_futures=False)

    def _run(self, spec: DownloadSpec, control: DownloadControl) -> DownloadSnapshot:
        try:
            return self.manager.run(
                spec, control, self._record, verifier=self.verifier_for(spec)
            )
        finally:
            with self._lock:
                if self._controls.get(spec.task_id) is control:
                    self._controls.pop(spec.task_id, None)

    def _record(self, snapshot: DownloadSnapshot) -> None:
        with self._lock:
            self._snapshots[snapshot.spec.task_id] = snapshot
            if self.repository is not None:
                self.repository.save(snapshot)
        self.on_change(snapshot)

    def _require(self, task_id: str) -> DownloadSnapshot:
        try:
            return self._snapshots[task_id]
        except KeyError as error:
            raise KeyError(f"unknown download task: {task_id}") from error
