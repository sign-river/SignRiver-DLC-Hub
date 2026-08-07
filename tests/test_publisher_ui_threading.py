from __future__ import annotations

import ast
import inspect
import textwrap
import threading
import json
import zipfile
from queue import SimpleQueue
from types import SimpleNamespace

import signriver_publisher.ui as publisher_ui
from signriver_publisher.ui import PublisherApplication
from signriver_publisher.updates import UpdateReleaseDraft


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


def test_update_release_publish_runs_network_work_off_the_tk_thread() -> None:
    source = inspect.getsource(PublisherApplication.publish_update_release)

    assert 'name="update-release-publish"' in source
    assert "initialdir=self._update_package_dir()" in source
    assert "threading.Thread(" in source
    assert "self._post_ui(" in source
    assert "_publish_update_mirror" in source


def test_module_archive_publish_captures_tk_values_before_starting_worker() -> None:
    source = inspect.getsource(PublisherApplication.publish_module_archive)

    assert 'name="module-archive-publish"' in source
    assert 'archive_dir = self._module_archive_dir()' in source
    assert 'archive_dir.glob("SignRiver-DLC-Hub-module-v*.zip")' in source
    assert "filedialog.askopenfilename" not in source
    assert 'selected_owner = self.owner_entry.get().strip()' in source
    assert 'selected_repository = self.repo_entry.get().strip()' in source
    assert 'selected_token = self.token_entry.get().strip()' in source


def test_update_mirror_uploads_both_packages_before_either_manifest(tmp_path) -> None:
    package = tmp_path / "module.zip"
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr(
            "module.json",
            json.dumps(
                {
                    "version": "0.2.0",
                    "api_version": 1,
                    "entrypoint": "app_entry.py:create_application",
                }
            ),
        )
        archive.writestr(
            "app_entry.py", "def create_application(context): pass"
        )
    calls = []

    class Harness:
        settings = SimpleNamespace(
            owner="gitlink-owner", repository="assets", token="gitlink-token",
            github_owner="github-owner", github_repository="assets", github_token="github-token",
        )
        workspace = SimpleNamespace(output_dir=tmp_path / "output")

        def _publish_update_target(
            self, target, owner, repository, token, package, manifest, **progress
        ):
            calls.append(
                (
                    target,
                    package is not None,
                    manifest is not None,
                    progress.get("progress_start"),
                    progress.get("progress_total"),
                )
            )

    PublisherApplication._publish_update_mirror(
        Harness(), UpdateReleaseDraft("0.2.0", "module", package)
    )

    assert calls == [
        ("gitlink", True, False, 0, 4), ("github", True, False, 1, 4),
        ("gitlink", False, True, 2, 4), ("github", False, True, 3, 4),
    ]


def test_update_target_reports_github_upload_progress(monkeypatch, tmp_path) -> None:
    package = tmp_path / "update.zip"
    manifest = tmp_path / "update-manifest.json"
    package.write_bytes(b"x" * 12)
    manifest.write_bytes(b"{}")
    events = []

    class Client:
        def __init__(self, repository, token):
            pass

        def ensure_release(self, tag, *, name):
            return object()

        def upload_asset(
            self, release, path, *, replace_existing, progress
        ):
            progress(path.stat().st_size, path.stat().st_size)

    monkeypatch.setattr(publisher_ui, "GitHubReleaseClient", Client)
    harness = SimpleNamespace(
        _update_paths=PublisherApplication._update_paths,
        _queue_upload_progress=lambda *value: events.append(value),
    )

    PublisherApplication._publish_update_target(
        harness, "github", "owner", "repo", "token", package, manifest
    )

    assert (1, 2, "GitHub · update.zip", 12, 12) in events
    assert (2, 2, "GitHub · update-manifest.json", 2, 2) in events


def test_update_target_reports_gitlink_upload_progress(monkeypatch, tmp_path) -> None:
    package = tmp_path / "update.zip"
    package.write_bytes(b"x" * 12)
    events = []

    class Manager:
        def __init__(self, client, repository):
            pass

        def upload_file_to_release(
            self, tag, release_name, path, *, progress
        ):
            progress(path.stat().st_size, path.stat().st_size)

    monkeypatch.setattr(publisher_ui, "RemoteResourceManager", Manager)
    harness = SimpleNamespace(
        _update_paths=PublisherApplication._update_paths,
        _queue_upload_progress=lambda *value: events.append(value),
    )

    PublisherApplication._publish_update_target(
        harness, "gitlink", "owner", "repo", "token", package, None
    )

    assert (1, 1, "GitLink · update.zip", 12, 12) in events


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


def test_cartridge_management_owns_hub_generation_and_publish_workflow() -> None:
    source = inspect.getsource(PublisherApplication)

    assert 'self.tabs.add("卡带管理")' in source
    assert 'text="管理公告"' in source
    assert "def open_announcement_manager" in source
    assert "def preview_announcement" in source
    assert "def save_announcement" in source
    assert 'text="一键双端发布卡带"' in source
    assert "def publish_cartridge_hub_mirror" in source
    assert 'text="单源发布卡带中心"' in source
    assert "def publish_cartridge_hub" in source
    assert "hub_publish_assets" in source
    assert "self._publish_resume_context = (repo, profile, assets, token)" in source
    assert "无需手动上传" in source
    assert "请将这些文件上传到资源仓库" not in source


def test_publisher_tab_order_puts_cartridge_management_last() -> None:
    source = inspect.getsource(PublisherApplication._build_ui)

    games = source.index('self.tabs.add("卡带配置")')
    acceptance = source.index('self.tabs.add("发布验收")')
    management = source.index('self.tabs.add("卡带管理")')
    assert games < acceptance < management


def test_publisher_mutating_entry_points_use_single_writer_guard() -> None:
    guarded = (
        "import_dlc",
        "clear_local_resources",
        "build_all",
        "refresh_steam_data",
        "publish_release",
        "publish_cartridge_hub_mirror",
        "publish_cartridge_hub",
        "generate_client_hub",
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
