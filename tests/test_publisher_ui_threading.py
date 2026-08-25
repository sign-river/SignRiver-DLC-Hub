from __future__ import annotations

import ast
import inspect
import textwrap
import threading
import json
import zipfile
from queue import SimpleQueue
from types import SimpleNamespace

import signriver_publisher.release_center as release_center_ui
import signriver_publisher.ui as publisher_ui
from signriver_publisher.release_center import ReleaseCenter
from signriver_publisher.release_center_ui import ReleaseCenterUiMixin
from signriver_publisher.publisher_targets_ui import PublisherTargetsUiMixin
from signriver_publisher.release_models import CheckResult, ReleaseStatus
from signriver_publisher.release_service import ReleaseService
from signriver_publisher.ui import PublisherApplication


def _write_program_package(path, *, platform: str, version: str = "0.2.0"):
    manifest = {
        "schema_version": 1,
        "version": version,
        "target_platform": platform,
        "target_arch": "x64",
        "files": [],
    }
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("release-manifest.json", json.dumps(manifest))
        archive.writestr("payload.txt", platform)
    return path


def _publisher_ui_sources() -> str:
    return "\n".join(
        inspect.getsource(base)
        for base in PublisherApplication.__mro__
        if base.__module__.startswith("signriver_publisher.")
    )


class _UiHarness:
    def __init__(self) -> None:
        self._ui_events = SimpleQueue()
        self._ui_pump_running = True
        self._is_closing = False
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


def test_cartridge_management_owns_hub_generation_and_publish_workflow() -> None:
    source = _publisher_ui_sources()

    assert 'self.cartridges_tab = self.game_support_tabs.add("卡带与公告")' in source
    assert 'text="管理公告"' in source
    assert "def open_announcement_manager" in source
    assert "def preview_announcement" in source
    assert "def save_announcement" in source
    assert 'text="一键双端发布卡带"' in source
    assert "def publish_cartridge_hub_mirror" in source
    assert "hub_publish_assets" in source
    assert "self._publish_resume_context = (repo, profile, assets, token)" in source
    assert "无需手动上传" in source
    assert "请将这些文件上传到资源仓库" not in source


def test_publisher_uses_task_oriented_workspace_tabs() -> None:
    source = inspect.getsource(PublisherApplication._build_ui)
    content_source = inspect.getsource(PublisherApplication._build_content_workspace)
    support_source = inspect.getsource(PublisherApplication._build_game_support_workspace)
    account_source = inspect.getsource(PublisherApplication._build_account_test_workspace)

    release = source.index('self.tabs.add("发布包与归档")')
    resources = source.index('self.tabs.add("资源管理")')
    support = source.index('self.tabs.add("游戏支持数据")')
    accounts = source.index('self.tabs.add("账户与测试")')
    assert release < resources < support < accounts
    assert 'self.tabs.add("发布工作台")' not in source
    assert 'self.sources_tab = self.content_tabs.add("本地资源")' in content_source
    assert 'self.upload_queue_tab = self.content_tabs.add("上传队列")' in content_source
    assert 'self.remote_tab = self.content_tabs.add("远端维护")' in content_source
    assert 'self.games_tab = self.game_support_tabs.add("游戏配置")' in support_source
    assert 'self.cartridges_tab = self.game_support_tabs.add("卡带与公告")' in support_source
    assert 'self.publisher_targets_tab = self.account_tabs.add("发布目标")' in account_source
    assert 'self.account_tabs.add("兼容发布")' not in account_source
    assert 'self.remote_tab = self.account_tabs.add("远端维护")' not in account_source
    assert 'self.acceptance_tab = self.account_tabs.add("人工验收")' in account_source
    assert "CTkTabview" not in inspect.getsource(PublisherApplication._nested_tabs)


def test_publisher_mutating_entry_points_use_single_writer_guard() -> None:
    guarded = (
        "import_dlc",
        "clear_local_resources",
        "refresh_steam_data",
        "publish_cartridge_hub_mirror",
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

    # 发布入口必须在用户确认后才由实际启动器占用写锁；否则只读
    # 检查或取消确认会留下幽灵“正在上传”状态。
    publish_source = inspect.getsource(PublisherApplication.publish_release)
    start_source = inspect.getsource(PublisherApplication._start_publish)
    assert "_removed_single_source_action" in publish_source
    assert "_begin_background_mutation" in start_source


def test_read_only_remote_refresh_does_not_block_publisher_close() -> None:
    refresh_source = inspect.getsource(PublisherApplication.refresh_remote_resources)
    guard_source = inspect.getsource(PublisherApplication._begin_remote_operation)

    assert 'mutating=False' in refresh_source
    assert 'if mutating and not self._begin_background_mutation(' in guard_source


def test_remote_maintenance_uses_saved_target_settings_not_removed_legacy_entries() -> None:
    source = inspect.getsource(PublisherApplication._github_repository_client)
    gitlink_source = inspect.getsource(PublisherApplication._remote_manager)

    assert "self.settings.github_owner" in source
    assert "self.settings.github_repository" in source
    assert "self.settings.github_token" in source
    assert "self.owner_entry" not in source
    assert "self.repo_entry" not in source
    assert "self.token_entry" not in source
    assert "self.settings.token" in gitlink_source


def test_cartridge_mirror_save_hook_uses_settings_not_removed_legacy_entries() -> None:
    source = inspect.getsource(PublisherApplication._save_active_settings)

    assert "self.settings.save(self.settings_path)" in source
    assert "self.owner_entry" not in source
    assert "self.repo_entry" not in source
    assert "self.token_entry" not in source


def test_cartridge_mirror_button_state_uses_only_modular_controls() -> None:
    source = inspect.getsource(PublisherApplication._set_publish_buttons_available)

    assert "hub_publish_button" in source
    assert "self.publish_button" not in source
    assert "self.publish_update_button" not in source


def test_removed_legacy_publish_entrypoints_cannot_fall_back_to_legacy_widgets() -> None:
    for name in (
        "publish_release",
        "publish_module_archive",
        "publish_cartridge_hub",
        "adopt_remote_assets",
        "_publish_scope_controls",
    ):
        source = inspect.getsource(getattr(PublisherApplication, name))
        assert "self.owner_entry" not in source, name
        assert "self.publish_button" not in source, name


def test_local_resource_cards_offer_folder_rescan() -> None:
    source = inspect.getsource(PublisherApplication._build_sources_tab)
    resource_header = inspect.getsource(PublisherApplication._resource_header)

    assert source.count("self.refresh_resource_lists") == 2
    assert 'text="刷新列表"' in resource_header
    assert "def refresh_resource_lists" in _publisher_ui_sources()


def test_content_build_uses_a_separate_queue_without_locking_other_game_controls() -> None:
    source = _publisher_ui_sources()
    build_source = inspect.getsource(PublisherApplication._start_next_content_build)

    assert "ContentBuildQueue(workspace.root)" in inspect.getsource(PublisherApplication)
    assert 'self.content_tabs.add("构建队列")' in source
    assert 'text="加入构建队列"' in source
    assert 'text="查看上传队列"' in source
    assert "self._begin_background_mutation" not in build_source
    assert "steam_button" not in build_source
    assert "game_menu.configure" not in build_source
    assert "def _queue_build_progress" in source
    assert "def _flush_build_progress" in source


def test_build_queue_requires_explicit_start_and_can_enqueue_all_games() -> None:
    enqueue_source = inspect.getsource(PublisherApplication._queue_current_game_build)
    enqueue_all_source = inspect.getsource(PublisherApplication._enqueue_all_games_for_build)
    start_source = inspect.getsource(PublisherApplication._start_all_content_builds)
    next_source = inspect.getsource(PublisherApplication._start_next_content_build)
    tab_source = inspect.getsource(PublisherApplication._build_build_queue_tab)

    assert "self._start_next_content_build()" not in enqueue_source
    assert "self.workspace.list_games()" in enqueue_all_source
    assert "self.content_build_queue.enqueue(profile)" in enqueue_all_source
    assert "self._build_queue_run_requested = True" in start_source
    assert "self._start_next_content_build()" in start_source
    assert "if not self._build_queue_run_requested:" in next_source
    assert 'text="全部加入构建队列"' in tab_source
    assert 'text="开始全部构建"' in tab_source


def test_rebuild_replaces_an_existing_active_upload_queue_record() -> None:
    source = inspect.getsource(PublisherApplication._build_done)

    assert "self.content_upload_queue.active_for_game(profile.game_id)" in source
    assert "self._enqueue_built_game_item" in source


def test_build_queue_can_batch_enqueue_completed_items_in_order() -> None:
    source = inspect.getsource(PublisherApplication._enqueue_all_built_game_uploads)
    upload_source = inspect.getsource(PublisherApplication._start_upload_queue_item)

    assert "if item.status is BuildQueueStatus.COMPLETED" in source
    assert "_enqueue_built_game_item" in source
    assert "_create_game_content_batch_for_profile" not in source
    assert "threading.Thread" not in source
    assert "preview_game_content_mirror" not in source
    assert "preview_game_content_mirror" in upload_source


def test_single_built_game_enqueue_refreshes_and_opens_the_upload_queue() -> None:
    source = inspect.getsource(PublisherApplication._enqueue_built_game_upload)

    assert "self._render_upload_queue()" in source
    assert "self._render_build_queue()" in source
    assert 'self.content_tabs.set("上传队列")' in source
    assert "messagebox.showerror" in source


def test_build_queue_header_does_not_mix_geometry_managers() -> None:
    source = inspect.getsource(PublisherApplication._build_build_queue_tab)

    assert "header_actions.grid(" in source
    assert "header_actions, text=\"一键加入上传队列\"" in source
    assert "header, text=\"一键加入上传队列\"" not in source


def test_build_queue_logs_preserved_empty_dlc_directly() -> None:
    source = inspect.getsource(PublisherApplication._queue_build_progress)

    assert 'stage == "保留空目录"' in source


def test_game_configuration_form_uses_an_internal_scroll_container() -> None:
    source = inspect.getsource(PublisherApplication._build_games_tab)

    assert "card = ctk.CTkScrollableFrame(" in source
    assert "self._card(self.games_tab, 0, \"游戏卡带配置\")" not in source
    assert "height=32" in source


def test_content_release_page_has_a_bounded_operation_log_for_user_and_background_events() -> None:
    source = inspect.getsource(PublisherApplication._build_content_release_tab)
    log_source = inspect.getsource(PublisherApplication._log)
    upload_source = inspect.getsource(PublisherApplication._upload_queue_item_started)

    assert '"操作日志"' in source
    assert "CTkTextbox" in source
    assert "activate_scrollbars=True" in source
    assert "_content_operation_log_lines" in source
    assert "strftime('%H:%M:%S')" in log_source
    assert "del lines[:-500]" in log_source
    assert "visible_lines = lines[-8:]" in log_source
    assert 'widget.insert("1.0", "\\n".join(lines))' in log_source
    queue_source = inspect.getsource(PublisherApplication._queue_current_game_build)
    assert "覆盖“{self.profile.display_name}”原有" in queue_source
    assert "当前构建结束后将舍弃旧结果并重新构建" in queue_source
    assert "后台任务：开始上传" in upload_source
    assert "OperationLog" in source
    assert "_content_operation_history.load()" in source
    assert "history.append(line)" in log_source


def test_content_release_page_uses_a_scrollable_router_page_for_small_windows() -> None:
    router_source = inspect.getsource(publisher_ui._PageRouter.add)
    workspace_source = inspect.getsource(PublisherApplication._build_content_workspace)

    assert "scrollable: bool = False" in router_source
    assert "ctk.CTkScrollableFrame" in router_source
    assert 'self.content_tabs.add("DLC / 补丁发布", scrollable=True)' in workspace_source


def test_running_build_item_does_not_create_an_empty_action_frame() -> None:
    source = inspect.getsource(PublisherApplication._render_build_queue_item)

    assert "if item.status is not BuildQueueStatus.RUNNING:" in source
    assert "Empty CTkFrame instances retain their default height" in source


def test_remote_maintenance_toolbar_keeps_only_resource_operations() -> None:
    source = inspect.getsource(PublisherApplication._build_remote_tab)

    assert 'text="刷新远程"' in source
    assert 'text="选择文件上传"' in source
    assert 'text="批次诊断"' not in source
    assert 'text="导出审计"' not in source


def test_remote_maintenance_uses_a_summary_and_sidebar_for_change_details() -> None:
    source = inspect.getsource(PublisherApplication._build_remote_tab)

    assert "self.remote_detail_sidebar" in source
    assert 'text="变更清单"' in source
    assert 'text="云端详情"' in source
    assert "self.remote_diff_summary" in source
    assert "_select_remote_detail_page" in source


def test_game_content_queue_does_not_require_gitlink_cli() -> None:
    source = inspect.getsource(PublisherApplication._release_center_providers)

    assert "GitLinkCli" not in source


def test_stale_upload_snapshot_tells_operator_to_requeue_the_completed_build() -> None:
    source = inspect.getsource(PublisherApplication._start_upload_queue_item)

    assert "排队时的旧发布记录不一致" in source
    assert "无需重复构建" in source


def test_superseded_upload_preflight_never_confirms_the_old_build() -> None:
    source = inspect.getsource(PublisherApplication._confirm_upload_queue_remote_preview)

    assert "latest.release_id != plan.batch_id" in source
    assert "self.content_upload_queue.requeue_latest(item_id)" in source
    assert "将重新读取最新构建的云端差异" in source


def test_upload_queue_releases_its_reservation_when_fifo_start_is_rejected() -> None:
    source = inspect.getsource(PublisherApplication._upload_queue_item_start_failed)

    assert 'self._end_background_mutation("upload-queue")' in source
    assert "self._queue_current_item_id = None" in source


def test_upload_queue_claims_fifo_item_in_worker_before_remote_preflight() -> None:
    source = inspect.getsource(PublisherApplication._start_upload_queue_item)

    assert "threading.Thread" in source
    assert "self.content_upload_queue.mark_running(item_id)" in source
    assert "self._post_ui(" in source
    assert "self._upload_queue_item_started" in source


def test_stale_upload_item_does_not_offer_a_bypass_for_the_failed_snapshot() -> None:
    item_source = inspect.getsource(PublisherApplication._render_upload_queue_item)

    assert 'text="使用当前构建"' not in item_source
    assert not hasattr(PublisherApplication, "_refresh_upload_queue_item_from_build")


def test_remote_resource_refresh_renders_a_metadata_only_change_preview() -> None:
    source = inspect.getsource(PublisherApplication._fill_remote_diff)
    remote_source = inspect.getsource(PublisherApplication._fill_remote_assets)

    assert "云端缓存命中：DLC 一致，将跳过上传" in source
    assert "每次更新，将替换云端同名文件" in source
    assert "将新增到云端" in source
    assert "asset.name.casefold()" in source
    assert "live_attachment_ids" in source
    assert "No remote attachment is downloaded" in source
    assert "云端保留（批量镜像发布时将删除）" in remote_source
    assert 'render_group("需要发布"' in source
    assert 'render_group("云端缓存命中（可复用 DLC）"' in source
    assert '_select_remote_detail_page("changes")' in source


def test_content_upload_log_reports_cache_reuse() -> None:
    source = inspect.getsource(PublisherApplication._upload_queue_item_finished)

    assert "云端附件缓存命中" in source
    assert "未重复上传" in source


def test_content_upload_log_records_each_file_before_the_game_finishes() -> None:
    source = inspect.getsource(PublisherApplication._log_upload_queue_activity)
    finished_source = inspect.getsource(PublisherApplication._upload_queue_item_finished)

    assert "上传成功，已记录远端附件 ID 与大小" in source
    assert "云端缓存命中：复用可信附件记录，未重复上传" in source
    assert 'stage.stage_id == "content.upload_snapshot"' in source
    assert "self._log_upload_queue_activity(plan)" in finished_source
    assert "全部文件已成功上传并发布 catalog.json" in finished_source


def test_build_queue_exposes_publisher_wide_compatibility_mode_instead_of_remote_toggle() -> None:
    build_source = inspect.getsource(PublisherApplication._build_build_queue_tab)
    remote_source = inspect.getsource(PublisherApplication._build_remote_tab)
    compatibility_source = inspect.getsource(PublisherApplication._set_build_queue_compatibility_mode)

    assert 'text="兼容发布：保留云端仅有文件"' in build_source
    assert "兼容发布：保留云端仅有文件" not in remote_source
    assert "save_preserve_remote_only_files(enabled)" in compatibility_source
    assert "已开启（保留云端仅有文件）" in inspect.getsource(
        PublisherApplication._render_build_queue_compatibility_status
    )
    assert 'text="旧版补丁名兼容"' in build_source
    assert "save_legacy_patch_asset_aliases_enabled(enabled)" in inspect.getsource(
        PublisherApplication._set_legacy_patch_alias_mode
    )


def test_upload_queue_pause_recovers_a_stale_non_running_release_immediately() -> None:
    source = inspect.getsource(PublisherApplication._pause_upload_queue)

    assert "plan.status is ReleaseStatus.RUNNING" in source
    assert "self.content_upload_queue.mark_paused(item_id)" in source
    assert "self._end_background_mutation(\"upload-queue\")" in source


def test_bulk_upload_enqueue_is_local_and_defers_remote_preflight_to_execution() -> None:
    source = inspect.getsource(PublisherApplication._enqueue_all_built_game_uploads)
    upload_source = inspect.getsource(PublisherApplication._start_upload_queue_item)
    confirmation_source = inspect.getsource(PublisherApplication._confirm_upload_queue_remote_preview)

    assert "preview_game_content_mirror" not in source
    assert "_create_game_content_batch_for_profile" in upload_source
    assert "preview_game_content_mirror" in upload_source
    assert "确认本项云端变更" in confirmation_source


def test_comparison_page_keeps_only_its_specific_back_button() -> None:
    source = inspect.getsource(ReleaseCenter._build_comparison_page)

    assert "back_page=None" in source
    assert 'text="← 返回发布包与归档模块提交"' in source


def test_publisher_worker_functions_do_not_touch_obvious_tk_apis_directly() -> None:
    trees = [
        ast.parse(textwrap.dedent(source))
        for source in (
            inspect.getsource(base)
            for base in PublisherApplication.__mro__
            if base.__module__.startswith("signriver_publisher.")
        )
    ]
    workers = [
        node
        for tree in trees
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
        self._is_closing = False
        self.withdrawn = False
        self.destroyed = False

    def _active_background_mutations(self):
        return PublisherApplication._active_background_mutations(self)

    def withdraw(self) -> None:
        self.withdrawn = True

    def destroy(self) -> None:
        self.destroyed = True


def test_stale_upload_control_does_not_claim_background_upload() -> None:
    harness = _CloseHarness()
    harness._upload_control = object()

    assert PublisherApplication._active_background_mutations(harness) == ()


def test_publisher_close_allows_stale_upload_control_after_rejected_start() -> None:
    harness = _CloseHarness()
    harness._upload_control = object()

    PublisherApplication._close_publisher(harness)

    assert harness.destroyed
    assert harness.withdrawn
    assert harness._is_closing
    assert not harness._ui_pump_running


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
    assert harness.withdrawn
    assert harness._is_closing
    assert not harness._ui_pump_running


def test_publisher_close_hides_window_before_destroying() -> None:
    source = inspect.getsource(PublisherApplication._close_publisher)

    assert source.index("self.withdraw()") < source.index("self.destroy()")
    assert "self._is_closing = True" in source


def test_release_center_batch_sidebar_is_fixed_and_primary_actions_are_larger() -> None:
    source = inspect.getsource(ReleaseCenter._build_batches_page)
    home_source = inspect.getsource(ReleaseCenter._build_home_page)

    assert "grid_columnconfigure(0, weight=0, minsize=360)" in source
    assert "grid_columnconfigure(1, weight=1)" in source
    assert "history_card.grid_propagate(False)" in source
    assert "仅查看已保存的发布信息" in source
    assert 'text="归档 / 移除当前草稿"' not in source
    assert "self.board_content = ctk.CTkScrollableFrame" in source
    assert 'text="发布包与归档模块提交"' in home_source
    assert 'text="历史发布记录"' in home_source
    assert 'text="DLC 与补丁资源"' not in home_source
    assert "资源上传请使用" not in home_source
    assert 'text="当前发布状态"' not in home_source
    assert 'text="管理发布包与归档模块提交  →"' in home_source
    assert 'text="查看历史记录  →"' in home_source


def test_release_history_is_separated_from_the_active_release_context() -> None:
    source = inspect.getsource(ReleaseCenter)

    assert "def view_history_record" in source
    assert "self.viewed_history_batch_id = batch_id" in source
    assert "self.current_batch_id = batch_id" in inspect.getsource(ReleaseCenter.select)
    assert "command=lambda value=plan.batch_id: self.view_history_record(value)" in source
    assert "self._select_latest_record_as_current()" in source


def test_release_center_worker_posts_terminal_callbacks_and_releases_lease() -> None:
    source = inspect.getsource(PublisherApplication._execute_release_center_batch)
    done_source = inspect.getsource(PublisherApplication._release_center_finished)
    failed_source = inspect.getsource(PublisherApplication._release_center_failed)

    assert 'threading.Thread(' in source
    assert source.count('self._post_ui(') == 2
    assert 'messagebox.' not in source
    assert '.configure(' not in source
    assert '_end_background_mutation("release-center")' in done_source
    assert '_end_background_mutation("release-center")' in failed_source
    assert 'execute_game_content' in source
    assert 'execute_hub' in source


def test_release_center_restores_execute_button_when_lease_is_rejected() -> None:
    execute_button = _ButtonHarness()
    pause_button = _ButtonHarness()
    execution_status_label = _ButtonHarness()
    harness = SimpleNamespace(
        current_batch_id="batch",
        execute_button=execute_button,
        pause_button=pause_button,
        execution_status_label=execution_status_label,
        execute_batch=lambda *_args: False,
        _execution_done=lambda _plan: None,
        _execution_failed=lambda _error: None,
    )

    ReleaseCenter.execute(harness)

    assert execute_button.calls == [
        {"state": "disabled", "text": "执行中…"},
        {"state": "normal", "text": "执行 / 恢复"},
    ]
    assert {"state": "disabled", "text": "安全暂停（启动中）"} in pause_button.calls


def test_advanced_maintenance_delete_has_batch_scoped_second_confirmation() -> None:
    source = inspect.getsource(PublisherApplication.delete_all_remote_resources)
    confirmation = inspect.getsource(PublisherApplication._confirm_maintenance_authorization)

    assert '_confirm_maintenance_authorization(' in source
    assert 'prepare_maintenance(' in confirmation
    assert 'authorize_maintenance(' in confirmation
    assert '缺少关联批次' in confirmation
    assert 'simpledialog.askstring(' in confirmation
    for method in (PublisherApplication.delete_remote_resource,):
        assert '_confirm_maintenance_authorization(' in inspect.getsource(method)

    assert "_removed_single_source_action" in inspect.getsource(
        PublisherApplication.adopt_remote_assets
    )


def test_release_center_confirmation_summary_exposes_side_effects(tmp_path) -> None:
    service = ReleaseService(tmp_path / "ws")
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    for platform in ("windows", "steamos", "macos"):
        _write_program_package(
            inbox / f"SignRiver-DLC-Hub-full-v0.2.0-{platform}-x64.zip",
            platform=platform,
        )
    plan = service.create_program_batch(
        version="0.2.0", inbox=inbox, notes="说明。建议尽快更新。",
        remote_targets={
            "gitlink": {"owner": "test-gitlink", "repository": "signriver-test"},
            "github": {"owner": "sign-river", "repository": "SignRiver-Test"},
        },
    )
    plan = service.preflight(plan.batch_id)
    summary = ReleaseCenter._confirmation_summary(plan)
    assert "SHA-256" in summary
    assert "GitLink：test-gitlink/signriver-test" in summary
    assert "GitHub：sign-river/SignRiver-Test" in summary
    assert "上传附件并切换更新清单" in summary
    assert "硬门禁、警告与跳过项" in summary


def test_release_center_shows_frozen_repository_targets() -> None:
    source = inspect.getsource(ReleaseCenter)

    assert "本次实际发布目标（创建时已冻结）" in source
    assert "self._publication_target_text(plan.remote_targets, frozen=True)" in source
    assert "下次创建发布将使用的发布目标" in source


def test_release_center_execution_uses_batch_frozen_targets() -> None:
    source = inspect.getsource(ReleaseCenterUiMixin._release_center_providers)

    assert "plan.remote_targets.get(provider, {})" in source
    assert "GitHubRepository(github_owner, github_repository)" in source
    assert "GitLinkRepository(gitlink_owner, gitlink_repository)" in source


def test_publisher_target_page_exposes_repositories_without_rendering_tokens() -> None:
    source = inspect.getsource(PublisherTargetsUiMixin)

    assert "发布账户与测试目标" not in source
    assert "账号配置" in source
    assert "保存 {provider} 目标" in source
    assert "def _save_publisher_target_settings" in source
    assert "def _test_publisher_target_connection" in source
    assert "测试连通性" in source
    assert "repository_info()" in source
    assert ".list_releases(" in source
    assert "self.tabs.set(\"高级维护\")" not in source
    assert "text=f\"{provider} 发布目标\"" in source
    assert "目标仓库：{repository_name}" in source
    assert "凭据状态：{credential_text}" in source
    assert "text=self.settings.token" not in source
    assert "text=self.settings.github_token" not in source


def test_release_center_cancelled_confirmation_does_not_freeze(monkeypatch) -> None:
    calls = []
    plan = SimpleNamespace(
        batch_id="batch",
        preflight=[SimpleNamespace(check_id="human.acceptance", result=CheckResult.PASS)],
    )
    harness = SimpleNamespace(
        current_batch_id="batch",
        service=SimpleNamespace(
            get=lambda _batch_id: plan,
            confirm=lambda _batch_id: calls.append("confirmed"),
        ),
        _confirmation_summary=lambda _plan: "summary",
        _render=lambda _plan: calls.append("rendered"),
    )
    monkeypatch.setattr(publisher_ui.messagebox, "askyesno", lambda *_args, **_kwargs: False)
    ReleaseCenter.confirm(harness)
    assert calls == []

def test_release_center_confirms_with_acceptance_warning_without_skip_reason(
    monkeypatch,
) -> None:
    calls = []
    plan = SimpleNamespace(batch_id="batch", preflight=[])
    harness = SimpleNamespace(
        current_batch_id="batch",
        service=SimpleNamespace(
            get=lambda _batch_id: plan,
            confirm=lambda _batch_id, **kwargs: calls.append(kwargs) or plan,
        ),
        _confirmation_summary=lambda _plan: "summary",
        _render=lambda _plan: calls.append("rendered"),
    )
    monkeypatch.setattr(
        release_center_ui.messagebox, "askyesno", lambda *_args, **_kwargs: True
    )

    ReleaseCenter.confirm(harness)

    assert calls == [{"skipped_acceptance_reason": None}, "rendered"]


def test_release_center_acceptance_warning_is_not_a_confirmation_blocker(
    monkeypatch,
) -> None:
    calls = []
    plan = SimpleNamespace(
        batch_id="batch",
        preflight=[SimpleNamespace(check_id="human.acceptance", result=CheckResult.WARNING)],
    )
    harness = SimpleNamespace(
        current_batch_id="batch",
        service=SimpleNamespace(
            get=lambda _batch_id: plan,
            confirm=lambda *_args, **_kwargs: calls.append("confirmed") or plan,
        ),
        _confirmation_summary=lambda _plan: "summary",
        _render=lambda _plan: calls.append("rendered"),
    )
    monkeypatch.setattr(
        release_center_ui.messagebox, "askyesno", lambda *_args, **_kwargs: True
    )

    ReleaseCenter.confirm(harness)

    assert calls == ["confirmed", "rendered"]


def test_release_center_directory_picker_starts_at_current_inbox() -> None:
    source = inspect.getsource(ReleaseCenter._choose_inbox)

    assert 'initialdir=str(initialdir)' in source
    assert 'current if current.is_dir() else self.default_inbox' in source


def test_release_center_local_file_comparison_provides_visible_feedback() -> None:
    source = inspect.getsource(ReleaseCenterUiMixin._capture_release_center_baseline)
    comparison_source = inspect.getsource(ReleaseCenter._render_local_remote_comparison)

    assert 'text="正在比较…"' in source
    assert "_render_local_remote_comparison(plan)" in source
    assert 'refresh_history()' in source
    assert 'local_changes["新增"].update(added)' in comparison_source
    assert 'local_changes["同名替换"].update(replaced)' in comparison_source
    assert '仅云端保留：{name}' in comparison_source
    assert 'self.show_page("comparison")' in comparison_source


def test_release_center_renders_operator_facing_batch_labels() -> None:
    source = inspect.getsource(ReleaseCenter)

    assert '程序更新' in source
    assert '待冻结确认' in source
    assert '收件文件' in source
    assert '发布编号（仅用于支持与排障）' in source
    assert '归档 / 移除草稿' not in source
    assert 'self.history, text=label, anchor="w", height=66' in source
    assert 'anchor="w", justify="left", height=54' not in source


def test_release_center_uses_replaceable_pages_for_specialist_operations() -> None:
    source = inspect.getsource(ReleaseCenter)

    assert 'self.page_container' in source
    assert 'page.grid_remove()' in source
    assert 'def show_page(self, name: str)' in source
    assert 'self._build_home_page()' in source
    assert 'self._build_preparation_page()' in source
    assert 'self._build_comparison_page()' in source
    assert 'self._build_batches_page()' in source
    assert 'self._build_baseline_page()' not in source
    assert 'self._build_preflight_page()' in source
    assert 'self._build_execution_page()' in source
    assert 'self.show_page("batches")' in source
    assert 'text="管理发布包与归档模块提交  →"' in source
    assert 'text="验证并查看差异"' in source
    assert 'text="发布文件  →"' in source
    assert 'def publish_program_files(self) -> None' in source
    assert 'def start_program_publish(self) -> None' in source
    assert 'def select(self, batch_id: str, *, show_history: bool = True)' in source
    assert 'self.select(plan.batch_id, show_history=False)' in source
    board_source = inspect.getsource(ReleaseCenter._build_batches_page)
    assert 'text="远端核对记录"' in board_source
    assert '读取远端基线（只读）' not in board_source
    assert '导出基线 JSON' not in board_source
    assert '仅查看已保存的发布信息' in board_source
    assert 'height=150' in source


class _ButtonHarness:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.values: dict[str, object] = {}

    def configure(self, **kwargs) -> None:
        self.calls.append(kwargs)
        self.values.update(kwargs)

    def cget(self, key: str):
        return self.values.get(key, "")


def test_release_center_preflight_waits_for_explicit_start_before_upload() -> None:
    calls: list[object] = []
    plan = SimpleNamespace(
        batch_id="batch",
        status=ReleaseStatus.AWAITING_CONFIRMATION,
    )
    execute_button = _ButtonHarness()
    execution_status_label = _ButtonHarness()
    harness = SimpleNamespace(
        current_batch_id="batch",
        execute_button=execute_button,
        execution_status_label=execution_status_label,
        _ensure_program_batch=lambda: (plan, False),
        select=lambda *args, **kwargs: calls.append(("select", args, kwargs)),
        refresh_history=lambda: calls.append("history"),
        show_page=lambda name: calls.append(("page", name)),
        service=SimpleNamespace(
            preflight=lambda batch_id: calls.append(("preflight", batch_id)) or plan,
            get=lambda batch_id: calls.append(("get", batch_id)) or plan,
            confirm=lambda batch_id: calls.append(("confirm", batch_id)) or plan,
        ),
        _render=lambda value: calls.append(("render", value)),
        execute=lambda: calls.append("execute"),
    )

    ReleaseCenter.publish_program_files(harness)

    assert ("preflight", "batch") in calls
    assert ("confirm", "batch") not in calls
    assert "execute" not in calls
    assert execute_button.calls[-1] == {"state": "normal", "text": "开始发布"}

    ReleaseCenter.start_program_publish(harness)

    assert ("confirm", "batch") in calls
    assert calls[-2:] == [("render", plan), "execute"]


def test_release_center_execution_starts_progress_monitor_and_keeps_pause_for_running_state() -> None:
    calls: list[object] = []
    harness = SimpleNamespace(
        current_batch_id="batch",
        execute_button=_ButtonHarness(),
        pause_button=_ButtonHarness(),
        execution_status_label=_ButtonHarness(),
        execute_batch=lambda batch_id, on_done, on_error: calls.append(batch_id) or True,
        _execution_done=lambda _plan: None,
        _execution_failed=lambda _error: None,
        _refresh_execution_progress=lambda batch_id: calls.append(("monitor", batch_id)),
        _pause_requested=False,
    )

    ReleaseCenter.execute(harness)

    assert calls == ["batch", ("monitor", "batch")]
    assert harness._execution_in_progress is True
    assert {"state": "disabled", "text": "安全暂停（启动中）"} in harness.pause_button.calls


def test_release_center_progress_monitor_renders_running_stage_and_reschedules() -> None:
    calls: list[object] = []
    plan = SimpleNamespace(status=ReleaseStatus.RUNNING)
    harness = SimpleNamespace(
        current_batch_id="batch",
        _execution_in_progress=True,
        service=SimpleNamespace(get=lambda batch_id: calls.append(("get", batch_id)) or plan),
        _render=lambda value: calls.append(("render", value)),
        after=lambda delay, callback: calls.append(("after", delay)) or "after-id",
    )

    ReleaseCenter._refresh_execution_progress(harness, "batch")

    assert calls == [("get", "batch"), ("render", plan), ("after", 450)]
    assert harness._execution_monitor_after_id == "after-id"


def test_release_center_pause_marks_request_pending_until_safe_checkpoint() -> None:
    calls: list[object] = []
    harness = SimpleNamespace(
        current_batch_id="batch",
        pause_button=_ButtonHarness(),
        execution_status_label=_ButtonHarness(),
        pause_batch=lambda batch_id: calls.append(batch_id),
        _pause_requested=False,
    )

    ReleaseCenter.pause(harness)

    assert calls == ["batch"]
    assert harness._pause_requested is True
    assert {"state": "disabled", "text": "已请求安全暂停…"} in harness.pause_button.calls


def test_extension_management_ui_exposes_unified_publish_flow() -> None:
    source = _publisher_ui_sources()

    for text in (
        "发布资源统一管理",
        "卡带与公告",
        "扩展指南与工具",
        "浏览与维护",
        "生成与发布",
        "刷新资源概览",
        "全部游戏卡带",
        "管理公告",
        "打开指南目录",
        "打开工具目录",
        "预检并双端发布扩展",
        "publish_extensions_mirror",
    ):
        assert text in source
