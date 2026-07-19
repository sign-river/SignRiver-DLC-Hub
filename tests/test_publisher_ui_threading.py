from __future__ import annotations

import ast
import inspect
import textwrap
import threading
from queue import SimpleQueue

import signriver_publisher.ui as publisher_ui
from signriver_publisher.ui import PublisherApplication


class _UiHarness:
    def __init__(self) -> None:
        self._ui_events = SimpleQueue()
        self._ui_pump_running = True
        self._pending_upload_progress = None
        self._pending_upload_progress_lock = threading.Lock()
        self.progress = []
        self.scheduled = []

    def _show_upload_progress(self, *value) -> None:
        self.progress.append(value)

    def _drain_ui_events(self) -> None:
        PublisherApplication._drain_ui_events(self)

    def after(self, delay: int, callback) -> None:
        self.scheduled.append((delay, callback))


def test_publisher_ui_queue_runs_callbacks_in_main_pump() -> None:
    harness = _UiHarness()
    called = []

    PublisherApplication._post_ui(harness, lambda: called.append("done"))
    assert called == []

    PublisherApplication._drain_ui_events(harness)

    assert called == ["done"]
    assert harness.scheduled[0][0] == 40


def test_publisher_upload_progress_keeps_only_latest_sample() -> None:
    harness = _UiHarness()

    PublisherApplication._queue_upload_progress(harness, 1, 3, "first.zip", 10, 100)
    PublisherApplication._queue_upload_progress(harness, 1, 3, "first.zip", 80, 100)
    PublisherApplication._drain_ui_events(harness)

    assert harness.progress == [(1, 3, "first.zip", 80, 100)]


def test_publisher_stopped_pump_drops_callbacks_and_progress() -> None:
    harness = _UiHarness()
    harness._ui_pump_running = False
    called = []

    PublisherApplication._post_ui(harness, lambda: called.append("late"))
    PublisherApplication._queue_upload_progress(harness, 1, 1, "late.zip", 1, 1)
    PublisherApplication._drain_ui_events(harness)

    assert called == []
    assert harness.progress == []
    assert harness.scheduled == []
    assert harness._pending_upload_progress is None


def test_publisher_single_writer_rejects_overlapping_mutations(monkeypatch) -> None:
    harness = _CloseHarness()
    notices = []
    monkeypatch.setattr(
        publisher_ui.messagebox,
        "showinfo",
        lambda title, message: notices.append((title, message)),
    )

    assert PublisherApplication._begin_background_mutation(
        harness, "build", "正在构建发布文件"
    )
    assert not PublisherApplication._begin_background_mutation(
        harness, "remote", "正在处理 GitLink 远程资源"
    )

    assert harness._background_mutations == {"build": "正在构建发布文件"}
    assert notices and "正在构建发布文件" in notices[-1][1]

    PublisherApplication._end_background_mutation(harness, "build")
    assert PublisherApplication._begin_background_mutation(
        harness, "remote", "正在处理 GitLink 远程资源"
    )


def test_publisher_paused_publish_can_resume_but_blocks_other_writers(
    monkeypatch,
) -> None:
    harness = _CloseHarness()
    harness._background_mutations["publish"] = "正在上传 Release"
    notices = []
    monkeypatch.setattr(
        publisher_ui.messagebox,
        "showinfo",
        lambda title, message: notices.append((title, message)),
    )

    assert PublisherApplication._begin_background_mutation(
        harness, "publish", "正在上传 Release", resume=True
    )
    assert not PublisherApplication._begin_background_mutation(
        harness, "build", "正在构建发布文件"
    )
    assert harness._background_mutations == {"publish": "正在上传 Release"}
    assert notices and "正在上传 Release" in notices[-1][1]


def test_publisher_pause_keeps_single_writer_reservation() -> None:
    paused_source = inspect.getsource(PublisherApplication._publish_paused)
    done_source = inspect.getsource(PublisherApplication._publish_done)
    failed_source = inspect.getsource(PublisherApplication._publish_failed)

    assert "_end_background_mutation" not in paused_source
    assert '_end_background_mutation("publish")' in done_source
    assert '_end_background_mutation("publish")' in failed_source


def test_publisher_mutating_entry_points_use_single_writer_guard() -> None:
    guarded = (
        "import_dlc",
        "clear_local_resources",
        "build_all",
        "refresh_steam_data",
        "publish_release",
        "_begin_remote_operation",
        "_run_action",
        "save_profile",
        "add_game",
        "create_repository",
    )

    for name in guarded:
        source = inspect.getsource(getattr(PublisherApplication, name))
        assert "_begin_background_mutation" in source, name


def test_publisher_worker_functions_do_not_touch_obvious_tk_apis_directly() -> None:
    tree = ast.parse(textwrap.dedent(inspect.getsource(PublisherApplication)))
    workers = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and (node.name == "work" or node.name == "_publish_worker")
    ]

    class DirectWorkerUiVisitor(ast.NodeVisitor):
        forbidden_attributes = {
            "after", "after_idle", "configure", "delete", "destroy",
            "grid", "insert", "pack", "see", "set", "winfo_exists",
        }

        def __init__(self) -> None:
            self.calls = []

        def visit_Lambda(self, _node: ast.Lambda) -> None:
            # UI callbacks passed to _post_ui intentionally contain Tk calls;
            # their bodies execute later in the main-loop pump.
            return

        def visit_Call(self, node: ast.Call) -> None:
            function = node.func
            if (
                isinstance(function, ast.Attribute)
                and (
                    function.attr in self.forbidden_attributes
                    or function.attr in {"_log", "_show_upload_progress"}
                    or function.attr.endswith(
                        ("_done", "_failed", "_loaded", "_paused")
                    )
                    or function.attr.startswith("show")
                    or function.attr.startswith("ask")
                )
            ):
                self.calls.append(node)
            self.generic_visit(node)

    visitor = DirectWorkerUiVisitor()
    for worker in workers:
        visitor.visit(worker)

    assert workers
    assert visitor.calls == []


class _AcceptanceHarness:
    @staticmethod
    def active_preparations():
        return ()


class _CloseHarness:
    def __init__(self) -> None:
        self.acceptance = _AcceptanceHarness()
        self._background_mutations = {}
        self._build_operation_active = False
        self._remote_operation_active = False
        self._upload_control = None
        self._ui_pump_running = True
        self.destroyed = False

    def _active_background_mutations(self):
        return PublisherApplication._active_background_mutations(self)

    def destroy(self) -> None:
        self.destroyed = True


def test_publisher_close_blocks_active_upload_without_stopping_pump(
    monkeypatch,
) -> None:
    harness = _CloseHarness()
    harness._upload_control = object()
    harness._background_mutations["publish"] = "正在上传 Release"
    warnings = []
    monkeypatch.setattr(
        publisher_ui.messagebox,
        "showwarning",
        lambda title, message: warnings.append((title, message)),
    )

    PublisherApplication._close_publisher(harness)

    assert not harness.destroyed
    assert harness._ui_pump_running
    assert warnings and "暂停发布" in warnings[0][1]
    assert "发布已暂停" in warnings[0][1]


def test_publisher_close_blocks_paused_publish_reservation(monkeypatch) -> None:
    harness = _CloseHarness()
    harness._background_mutations["publish"] = "正在上传 Release"
    warnings = []
    monkeypatch.setattr(
        publisher_ui.messagebox,
        "showwarning",
        lambda title, message: warnings.append((title, message)),
    )

    PublisherApplication._close_publisher(harness)

    assert not harness.destroyed
    assert harness._ui_pump_running
    assert warnings and "正在上传 Release" in warnings[0][1]


def test_publisher_close_blocks_other_background_mutation(monkeypatch) -> None:
    harness = _CloseHarness()
    harness._background_mutations["steam-refresh"] = "正在刷新 Steam 数据"
    warnings = []
    monkeypatch.setattr(
        publisher_ui.messagebox,
        "showwarning",
        lambda title, message: warnings.append((title, message)),
    )

    PublisherApplication._close_publisher(harness)

    assert not harness.destroyed
    assert harness._ui_pump_running
    assert warnings and "正在刷新 Steam 数据" in warnings[0][1]


def test_publisher_idle_close_stops_pump_then_destroys() -> None:
    harness = _CloseHarness()

    PublisherApplication._close_publisher(harness)

    assert harness.destroyed
    assert not harness._ui_pump_running
