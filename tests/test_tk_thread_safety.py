"""回归：tkinter 终结器不得在后台线程里调用 Tcl。

macOS 的 Tk 没有开启线程支持。后台线程触发 GC 回收 tkinter 字体对象时会
执行 Tcl 的 ``font delete``，进程直接以 EXC_BAD_ACCESS 退出。守护逻辑见
``app/versions/0.1.0/signriver_app/infrastructure/tk_thread_safety.py``。
"""

from __future__ import annotations

import threading
import tkinter
import tkinter.font as tkinter_font
from pathlib import Path
from typing import Any

from signriver_app.infrastructure.tk_thread_safety import (
    flush_pending,
    install,
    pending_count,
)

APP_ENTRY = Path(__file__).parents[1] / "app" / "versions" / "0.1.0" / "app_entry.py"


class _RecordingTcl:
    """记录每次 Tcl 调用及其发生线程的假 Tcl 解释器。"""

    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []
        self.threads: list[threading.Thread] = []

    def call(self, *args: Any) -> str:
        self.calls.append(args)
        self.threads.append(threading.current_thread())
        return ""


def _synthetic_font(tcl: _RecordingTcl, name: str) -> Any:
    """绕过 ``Font.__init__`` 造一个字体对象，避免真的连接 Tcl。"""
    font = tkinter_font.Font.__new__(tkinter_font.Font)
    font._tk = tcl
    font._call = tcl.call
    font.name = name
    font.delete_font = True
    return font


def test_install_guards_tk_finalizers_idempotently() -> None:
    assert install() is True
    assert install() is True

    for cls in (tkinter_font.Font, tkinter.Variable, tkinter.Image):
        assert getattr(cls.__del__, "_signriver_deferred", False) is True


def test_worker_thread_collection_defers_tcl_call_to_main_thread() -> None:
    install()
    tcl = _RecordingTcl()
    holder = [_synthetic_font(tcl, "f-worker")]
    baseline = pending_count()

    thread = threading.Thread(target=holder.clear)
    thread.start()
    thread.join()

    # 工作线程里绝不能发出 font delete，只能登记待处理。
    assert tcl.calls == []
    assert pending_count() == baseline + 1

    assert flush_pending() >= 1

    assert tcl.calls == [("font", "delete", "f-worker")]
    assert tcl.threads == [threading.main_thread()]
    assert pending_count() == baseline


def test_main_thread_collection_still_releases_tcl_resources() -> None:
    install()
    tcl = _RecordingTcl()
    font = _synthetic_font(tcl, "f-main")

    del font

    assert tcl.calls == [("font", "delete", "f-main")]


def test_client_installs_guard_and_flushes_from_ui_pump() -> None:
    source = APP_ENTRY.read_text(encoding="utf-8")

    assert "install_tk_finalizer_guard()" in source
    assert "flush_tk_finalizers(limit=200)" in source
