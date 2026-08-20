from __future__ import annotations

import logging
from collections.abc import Callable
from queue import Empty
from tkinter import TclError, messagebox

LOGGER = logging.getLogger(__name__)


class PublisherUiRuntimeMixin:
    """Main-thread callback pump and single-writer coordination for publisher UI."""

    def _post_ui(self, callback: Callable[[], None]) -> None:
        """Transfer work to Tk's owning thread without calling Tk directly."""
        if self._ui_pump_running and not self._is_closing:
            self._ui_events.put(callback)

    def _begin_background_mutation(
        self, key: str, label: str, *, resume: bool = False
    ) -> bool:
        """Acquire the publisher's single-writer reservation on the Tk thread.

        The publisher has several independent tabs, but their write operations
        share the same workspace and Release. Serializing them here prevents a
        build from racing a source edit and prevents two Release updates from
        replacing each other's attachment list. A paused publish retains its
        reservation and may reacquire only that same key when it resumes.
        """
        registered = set(self._background_mutations)
        if resume and registered == {key}:
            return True
        # 本地构建是按游戏隔离的 FIFO 工作，不应阻止操作人切换到另一款游戏
        # 继续导入、整理或保存卡带；它仍由 _active_background_mutations() 保护退出。
        active = tuple(dict.fromkeys(self._background_mutations.values()))
        if active:
            detail = "\n".join(f"• {value}" for value in active)
            messagebox.showinfo(
                "操作正在进行",
                f"请等待当前操作完成后再试：\n{detail}",
            )
            return False
        self._background_mutations[key] = label
        return True

    def _end_background_mutation(self, key: str) -> None:
        """Mark a registered background write operation as terminal."""
        self._background_mutations.pop(key, None)

    def _active_background_mutations(self) -> tuple[str, ...]:
        """Return stable, de-duplicated descriptions for close protection."""
        active = dict(self._background_mutations)
        if self._build_operation_active:
            active.setdefault("build", "正在构建发布文件")
        if self._remote_operation_active:
            active.setdefault("remote", "正在处理 GitLink 远程资源")
        # UploadControl is only a pause signal for a worker that has already
        # reserved a background mutation.  It can remain briefly after a
        # rejected start or a terminal callback, so it must never by itself
        # claim that a Release upload is active or prevent normal shutdown.
        return tuple(dict.fromkeys(active.values()))

    @staticmethod
    def _reset_scrollable_frame(frame) -> None:
        """Synchronize a rebuilt CTk scroll canvas and show its first row."""
        try:
            frame.update_idletasks()
            canvas = frame._parent_canvas
            bounds = canvas.bbox("all")
            if bounds is not None:
                canvas.configure(scrollregion=bounds)
            canvas.yview_moveto(0.0)
        except (AttributeError, TclError):
            return

    def _schedule_scrollable_reset(self, frame) -> None:
        """Reset a rebuilt scroll list after Tk has propagated row geometry."""
        def after_layout() -> None:
            try:
                self.after(20, lambda: self._reset_scrollable_frame(frame))
            except TclError:
                return

        try:
            self.after_idle(after_layout)
        except TclError:
            return

    def _queue_upload_progress(
        self, index: int, total: int, name: str, sent: int, size: int
    ) -> None:
        """Keep only the newest high-frequency upload progress sample."""
        if not self._ui_pump_running or self._is_closing:
            return
        with self._pending_upload_progress_lock:
            if not self._ui_pump_running or self._is_closing:
                return
            self._pending_upload_progress = (index, total, name, sent, size)

    def _drain_ui_events(self) -> None:
        if not self._ui_pump_running or self._is_closing:
            return
        for _ in range(250):
            try:
                callback = self._ui_events.get_nowait()
            except Empty:
                break
            try:
                callback()
            except Exception:
                LOGGER.exception("Unable to apply publisher UI event")
        with self._pending_upload_progress_lock:
            progress = self._pending_upload_progress
            self._pending_upload_progress = None
        if progress is not None:
            self._show_upload_progress(*progress)
        if self._ui_pump_running and not self._is_closing:
            try:
                self.after(40, self._drain_ui_events)
            except TclError:
                self._ui_pump_running = False
