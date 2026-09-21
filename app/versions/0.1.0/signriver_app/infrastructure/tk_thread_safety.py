"""把 tkinter 终结器发出的 Tcl 调用限制在主线程。

macOS 系统自带的 Tk 没有开启线程支持，任何非主线程发出的 Tcl 命令都可能
让进程直接段错误退出。已确认的崩溃调用链是 ``Tkapp_Call`` ->
``Tcl_EvalObjv`` -> ``Tk_FontObjCmd``，由后台线程里的 ``gc_collect_main``
触发：工作线程做文件扫描时分配对象导致分代回收，回收掉的字体对象在
``__del__`` 里执行 ``font delete``，于是在错误的线程上碰了 Tcl。

本客户端的后台线程本身不会直接操作控件（统一走 ``_post_ui``），但
``tkinter.font.Font``、``tkinter.Variable`` 和 ``tkinter.Image`` 的
``__del__`` 会释放 Tcl 资源，回收发生在哪个线程不受控。

``install()`` 包装这三个终结器：在工作线程被回收时只登记、不调用 Tcl；
``flush_pending()`` 由 UI 事件泵在主线程上真正执行清理。
"""

from __future__ import annotations

import threading
from typing import Callable

_PENDING: list[tuple[Callable[[object], None], object]] = []
_PENDING_LOCK = threading.Lock()
_INSTALLED = False
_FINALIZED_FLAG = "_signriver_tcl_finalized"


def _run_finalizer(original: Callable[[object], None], instance: object) -> None:
    if getattr(instance, _FINALIZED_FLAG, False):
        return
    try:
        setattr(instance, _FINALIZED_FLAG, True)
    except Exception:  # pragma: no cover - 防御性分支
        pass
    try:
        original(instance)
    except Exception:
        # 释放 Tcl 资源始终是尽力而为：解释器可能已经开始退出。
        pass


def _guard_finalizer(cls: type) -> None:
    original = cls.__dict__.get("__del__")
    if original is None or getattr(original, "_signriver_deferred", False):
        return

    def __del__(self, _original=original) -> None:
        if getattr(self, _FINALIZED_FLAG, False):
            return
        if threading.current_thread() is threading.main_thread():
            _run_finalizer(_original, self)
            return
        # 工作线程绝不调用 Tcl，只登记对象，交给 UI 事件泵。
        with _PENDING_LOCK:
            _PENDING.append((_original, self))

    __del__._signriver_deferred = True
    cls.__del__ = __del__


def install() -> bool:
    """包装 tkinter 终结器；重复调用无副作用。"""
    global _INSTALLED
    if _INSTALLED:
        return True
    try:
        import tkinter
        from tkinter import font as tkinter_font
    except Exception:  # pragma: no cover - 客户端必然带 tkinter
        return False
    for cls in (tkinter_font.Font, tkinter.Variable, tkinter.Image):
        _guard_finalizer(cls)
    _INSTALLED = True
    return True


def pending_count() -> int:
    with _PENDING_LOCK:
        return len(_PENDING)


def flush_pending(limit: int | None = None) -> int:
    """在调用线程（Tk 主线程）上执行被延后的终结器。"""
    with _PENDING_LOCK:
        batch = _PENDING[:limit] if limit is not None else list(_PENDING)
        if limit is None:
            _PENDING.clear()
        else:
            del _PENDING[: len(batch)]
    for original, instance in batch:
        _run_finalizer(original, instance)
    return len(batch)


__all__ = ["install", "flush_pending", "pending_count"]
