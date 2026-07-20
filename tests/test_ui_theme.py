from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace


APP_ENTRY = Path(__file__).parents[1] / "app" / "versions" / "0.1.0" / "app_entry.py"
PUBLISHER_UI = Path(__file__).parents[1] / "src" / "signriver_publisher" / "ui.py"


def _ui_palette() -> dict[str, str]:
    module = ast.parse(APP_ENTRY.read_text(encoding="utf-8"))
    assignment = next(
        node for node in module.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "UI" for target in node.targets)
    )
    return ast.literal_eval(assignment.value)


def _app_method(name: str):
    """Compile one UI method without constructing a Tk window."""
    module = ast.parse(APP_ENTRY.read_text(encoding="utf-8"))
    application = next(
        node for node in module.body
        if isinstance(node, ast.ClassDef) and node.name == "DlcHubApplication"
    )
    method = next(
        node for node in application.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == name
    )
    isolated = ast.fix_missing_locations(ast.Module(body=[method], type_ignores=[]))
    namespace = {}
    exec(compile(isolated, str(APP_ENTRY), "exec"), namespace)
    return namespace[name]


def test_ui_palette_uses_blue_white_design_tokens() -> None:
    palette = _ui_palette()

    assert palette["brand"] == "#3A7EBF"
    assert palette["primary"] == "#1976D2"
    assert palette["secondary"] == "#42A5F5"
    assert palette["page"] == "#F5F7FA"
    assert palette["card"] == "#FFFFFF"
    assert palette["panel"] == "#FAFAFA"


def test_ui_is_fixed_to_light_appearance() -> None:
    source = APP_ENTRY.read_text(encoding="utf-8")

    assert 'ctk.set_appearance_mode("Light")' in source
    assert 'ctk.set_appearance_mode("System")' not in source


def test_pages_use_fixed_responsive_host_instead_of_outer_scroll() -> None:
    source = APP_ENTRY.read_text(encoding="utf-8")

    assert 'container = ctk.CTkFrame(shell' in source
    assert 'self.page_host.pack(fill="both", expand=True)' in source
    assert 'self.dlc_list_frame.pack(fill="both", expand=True' in source
    assert 'compact = event.width < 1080' in source
    assert 'self.sidebar.configure(width=150 if compact else 174)' in source


def test_game_selector_has_visible_border_and_home_uses_github() -> None:
    source = APP_ENTRY.read_text(encoding="utf-8")

    assert 'self.game_selector = _combo_box(' in source
    assert '"border_color": UI["input_border"]' in source
    assert 'https://github.com/sign-river/SignRiver-DLC-Hub' in source
    assert '"github.com", "space.bilibili.com"' in source


def test_top_brand_area_warns_that_the_app_is_free_and_open_source() -> None:
    source = APP_ENTRY.read_text(encoding="utf-8")

    assert 'text="开源免费 · 付费购买请立即退款"' in source
    assert 'fg_color="#2F6FA9"' in source
    assert 'title_status_row.pack(anchor="w", pady=(3, 0))' in source
    assert "PRODUCT_TITLE_ZH" in source
    assert 'self.window.title(PRODUCT_TITLE_ZH)' in source
    assert 'text=PRODUCT_TITLE_ZH' in source
    assert 'text=AUTHOR_EN' in source
    assert 'text=AUTHOR_CN' in source
    assert 'AUTHOR_CN = "唏嘘南溪"' in source
    assert 'text="星河DLC"' in source
    assert 'text="一键解锁"' in source
    assert "def _apply_window_icon" in source
    assert "app.ico" in source


def test_all_dropdowns_use_bordered_combo_box_factory() -> None:
    source = APP_ENTRY.read_text(encoding="utf-8")

    assert "CTkOptionMenu(" not in source
    assert source.count("= _combo_box(") == 4
    assert '"border_width": 1' in source
    assert 'self.catalog_filter.set("全部状态")' in source
    assert 'self.log_level_filter.set("全部")' in source
    assert 'text="下载源"' in source
    assert "self.download_source_menu" in source
    assert "speed_test_url(self.user_settings.download_source)" in source
    assert "repository_home_url(self.user_settings.download_source)" in source


def test_catalog_defaults_to_simple_view_with_advanced_management() -> None:
    source = APP_ENTRY.read_text(encoding="utf-8")

    assert 'self.catalog_view_mode = "simple"' in source
    assert 'text="切换高级视图"' in source
    assert 'text="一键解锁"' in source
    assert "def _render_simple_catalog_rows" in source
    assert "def _render_advanced_catalog_rows" in source
    assert "def _simple_entry_status" in source
    assert "catalog_freshness" in source
    assert "def _freshness_status_text" in source


def test_catalog_commands_emphasize_unlock_and_align_secondary_actions() -> None:
    source = APP_ENTRY.read_text(encoding="utf-8")

    assert "catalog_command_bar = ctk.CTkFrame(" in source
    assert 'uniform="catalog-management"' in source
    assert "primary_action_panel = ctk.CTkFrame(" in source
    assert 'width=176,' in source
    assert 'height=50,' in source
    assert 'font=ctk.CTkFont(size=18, weight="bold")' in source
    assert 'widget is getattr(self, "download_selected_button", None)' in source
    assert 'self.download_selected_button.pack(padx=4, pady=4)' in source
    assert 'self.download_selected_button.pack(fill="both", expand=True' not in source
    assert '"primary_surface": "#EAF3FB"' in source
    assert 'getattr(self, "catalog_refresh_button", None)' in source
    assert 'getattr(self, "selection_toggle_button", None)' in source
    assert 'getattr(self, "repair_button", None)' in source


def test_log_commands_use_an_aligned_two_by_two_grid() -> None:
    source = APP_ENTRY.read_text(encoding="utf-8")

    assert "log_command_area = ctk.CTkFrame(" in source
    assert "log_action_grid = ctk.CTkFrame(" in source
    assert 'uniform="log-actions"' in source
    assert source.count("log_action_grid, text=") == 4
    assert 'log_tools.grid_columnconfigure(1, weight=1)' in source


def test_catalog_view_toggle_resets_scroll_after_rebuilding_rows() -> None:
    source = APP_ENTRY.read_text(encoding="utf-8")

    assert "def _reset_scrollable_frame" in source
    assert "def _reset_catalog_scroll" in source
    assert 'bounds = canvas.bbox("all")' in source
    assert "canvas.configure(scrollregion=bounds)" in source
    assert "canvas.yview_moveto(0.0)" in source
    assert "def _schedule_catalog_scroll_reset" in source
    assert "self._schedule_catalog_scroll_reset()" in source


def test_catalog_views_are_persistent_and_first_build_is_incremental() -> None:
    source = APP_ENTRY.read_text(encoding="utf-8")
    toggle_method = source.split("def _toggle_catalog_view", 1)[1].split(
        "def _render_simple_catalog_rows", 1
    )[0]
    batch_method = source.split("def _render_catalog_batch", 1)[1].split(
        "@staticmethod", 1
    )[0]

    assert 'self.catalog_view_frames["simple"]' in source
    assert 'self.catalog_view_frames["advanced"]' in source
    assert "def _show_catalog_view_frame" in source
    assert "target.pack(fill=\"both\", expand=True" in source
    assert "self._show_catalog_view_frame(self.catalog_view_mode)" in toggle_method
    assert "self._render_catalog_rows()" in toggle_method
    assert "batch_size = 12 if mode == \"simple\" else 3" in batch_method
    assert "self.window.after(" in batch_method
    assert 'state["render_key"] = render_key' in source


def test_switch_and_empty_release_clear_both_persistent_catalog_views() -> None:
    source = APP_ENTRY.read_text(encoding="utf-8")
    select_method = source.split("def _select_game", 1)[1].split(
        "def _content_work_is_active", 1
    )[0]
    show_method = source.split("def _show_catalog(", 1)[1].split(
        "def _reconcile_catalog_cache", 1
    )[0]
    error_method = source.split("def _show_catalog_error(", 1)[1].split(
        "def _schedule_catalog_search", 1
    )[0]
    clear_views = _app_method("_clear_catalog_views")

    assert "self._clear_catalog_views(" in select_method
    assert "self.catalog_online = False" in select_method
    assert "if not entries:" in show_method
    assert "self._clear_catalog_views(" in show_method
    assert show_method.index("self._clear_catalog_views(") < show_method.index(
        "            return", show_method.index("if not entries:")
    )
    assert "if generation is not None and cartridge_id is not None:" in error_method
    assert 'self._clear_catalog_views("目录刷新失败，请重试")' in error_method
    assert 'self.download_selected_button.configure(' in error_method

    class Child:
        def __init__(self) -> None:
            self.destroyed = False

        def destroy(self) -> None:
            self.destroyed = True

    class Frame:
        def __init__(self) -> None:
            self.children = [Child(), Child()]

        def winfo_children(self):
            return tuple(self.children)

    class Label:
        def __init__(self, parent, *, text) -> None:
            self.text = text
            parent.label = self

        def grid(self, **_kwargs) -> None:
            return None

    states = {
        mode: {
            "catalog_rows": {"old": object()},
            "simple_status_labels": {"old": object()},
            "selection_widgets": {"old": object()},
            "entry_frames": {"old": object()},
            "name_labels": {"old": object()},
            "selection_vars": {"old": object()},
            "render_key": ("old",),
        }
        for mode in ("simple", "advanced")
    }
    frames = {mode: Frame() for mode in states}

    class Application:
        catalog_view_frames = frames
        catalog_view_widgets = states
        catalog_view_mode = "simple"

        def __init__(self) -> None:
            self.cancelled = False
            self.reset = []
            self.activated = None

        def _cancel_catalog_render(self) -> None:
            self.cancelled = True

        def _schedule_scrollable_reset(self, frame) -> None:
            self.reset.append(frame)

        def _activate_catalog_view_storage(self, mode) -> None:
            self.activated = mode

    clear_views.__globals__["ctk"] = SimpleNamespace(CTkLabel=Label)
    application = Application()
    clear_views(application, "正在读取新目录")

    assert application.cancelled is True
    assert application.activated == "simple"
    assert application.reset == list(frames.values())
    for mode, frame in frames.items():
        assert all(child.destroyed for child in frame.children)
        assert frame.label.text == "正在读取新目录"
        assert states[mode]["render_key"] is None
        assert all(
            not states[mode][key]
            for key in (
                "catalog_rows",
                "simple_status_labels",
                "selection_widgets",
                "entry_frames",
                "name_labels",
                "selection_vars",
            )
        )


def test_all_rebuilt_client_scroll_lists_reset_after_geometry_propagation() -> None:
    source = APP_ENTRY.read_text(encoding="utf-8")
    task_method = source.split("def _refresh_task_page", 1)[1].split(
        "def _task_status_text", 1
    )[0]
    catalog_method = source.split("def _render_catalog_rows", 1)[1].split(
        "def _reset_scrollable_frame", 1
    )[0]

    assert "self.window.after_idle(after_layout)" in source
    assert "self.window.after(" in source
    # Task scroll requests are coalesced so consecutive small downloads cannot
    # accumulate expensive update_idletasks callbacks.
    assert "self.task_scroll_after_id" in source
    assert "self.window.after_cancel(self.task_scroll_after_id)" in source
    assert "def _apply_scheduled_task_scroll" in task_method
    assert task_method.count("self._schedule_task_scroll(") >= 2
    assert "self._schedule_catalog_scroll_reset()" in catalog_method


def test_all_rebuilt_publisher_scroll_lists_reset_after_refresh() -> None:
    source = PUBLISHER_UI.read_text(encoding="utf-8")
    resources_method = source.split("def _fill_resources", 1)[1].split(
        "def _select_game", 1
    )[0]
    local_method = source.split("def _fill_local_outputs", 1)[1].split(
        "def _show_remote_message", 1
    )[0]
    remote_message_method = source.split("def _show_remote_message", 1)[1].split(
        "def _fill_remote_assets", 1
    )[0]
    remote_assets_method = source.split("def _fill_remote_assets", 1)[1].split(
        "def import_dlc", 1
    )[0]

    assert "def _reset_scrollable_frame" in source
    assert "self.after_idle(after_layout)" in source
    assert resources_method.count("self._schedule_scrollable_reset(parent)") == 2
    assert local_method.count(
        "self._schedule_scrollable_reset(self.local_output_list)"
    ) == 2
    assert "self._schedule_scrollable_reset(self.remote_asset_list)" in remote_message_method
    assert remote_assets_method.count(
        "self._schedule_scrollable_reset(self.remote_asset_list)"
    ) == 2


def test_simple_catalog_is_compact_and_has_complete_bulk_selection() -> None:
    source = APP_ENTRY.read_text(encoding="utf-8")

    assert "self.simple_catalog_columns = 5" in source
    assert "columns = 4 if compact else 5" in source
    assert "self.catalog_selection_initialized = False" in source
    assert "if entries:" in source
    assert "if not self._is_entry_installed(entry)" in source
    assert 'checkbox_width=18, checkbox_height=18' in source
    assert 'status.grid(row=0, column=2' in source
    assert "def _toggle_visible_selection" in source
    assert 'text="取消全选" if all_selected else "全选"' in source
    assert "all_selected = bool(selectable)" in source
    assert "self.selection_toggle_button" in source
    assert "self.select_visible_button" not in source
    assert "self.clear_visible_button" not in source
    assert "https://space.bilibili.com/504574253" in source
    assert 'group_number = "1061299021"' in source


def test_bulk_management_speed_test_and_complete_task_cleanup_are_available() -> None:
    source = APP_ENTRY.read_text(encoding="utf-8")

    assert 'text="GitHub"' in source
    assert 'text="清除全部记录"' in source
    assert "self.download_queue.clear_all()" in source
    assert 'self._set_batch_download_state("idle")' in source
    assert "_apply_batch_download_button" not in source
    assert 'text="网络测速"' in source
    assert 'text="开始测速"' in source
    assert "measure_download_speed(url)" in source
    assert "speed_test_url(self.user_settings.download_source)" in source
    assert 'text="一键移除补丁"' in source
    assert 'text="恢复游戏原版"' in source
    assert 'text="卸载全部 DLC"' in source
    assert "def _uninstall_all_dlc" in source
    assert "remove_installed_dlc(game_root, dlc_id)" in source
    assert "uninstall.configure(state=\"normal\")" in source
    assert "符合 dlcNNN_<名称> 规则" not in source
    assert "当前资源目录和卡带规则确认" in source


def test_settings_separates_speed_cache_and_update_without_duplicate_about_page() -> None:
    source = APP_ENTRY.read_text(encoding="utf-8")

    assert 'text="网络测速"' in source
    assert 'text="缓存管理"' in source
    assert 'text="程序与更新"' in source
    assert 'text="下载容错"' in source
    assert 'text="永不因连接读取超时而中断"' in source
    assert "self.resilience_card" in source
    assert 'text="公告"' in source
    assert 'text="下次公告更新前不再显示"' in source
    assert "self.announcement_card" in source
    assert "def _refresh_announcement" in source
    assert "def _show_announcement_dialog" in source
    assert "_show_onboarding" not in source
    assert "def _help_label" in source
    assert "self.settings_help_labels" in source
    assert "wraplength=wraplength" in source
    assert 'text="下载源"' in source
    assert "self.source_card" in source
    assert "self.download_manager.configure_timeout" in source
    assert '"关于"' not in source
    assert "bandwidth_entry" not in source
    assert "限速 KiB/s" not in source
    assert "DownloadPolicy" not in source


def test_multi_game_async_results_are_scoped_and_file_changes_require_game_stopped() -> None:
    source = APP_ENTRY.read_text(encoding="utf-8")

    assert "self.game_selection_generation = 0" in source
    assert "self.game_selection_generation += 1" in source
    assert "generation != self.game_selection_generation" in source
    assert "cartridge_id != self.cartridge.cartridge_id" in source
    assert "def _require_game_stopped" in source
    assert 'self._require_game_stopped("一键解锁")' in source
    assert 'self._require_game_stopped("卸载全部 DLC")' in source
    assert 'self._require_game_stopped("移除补丁")' in source
    assert 'self._require_game_stopped("一键修复")' in source
    assert "game_state.running" in source


def test_batch_download_has_one_pause_control_and_thread_safe_ui_events() -> None:
    source = APP_ENTRY.read_text(encoding="utf-8")

    assert 'self.batch_download_state = "idle"' in source
    assert '"running": ("暂停下载", True)' in source
    assert '"paused": ("继续下载", True)' in source
    assert "def _pause_batch_download" in source
    assert "self.download_queue.pause_many(self.batch_download_task_ids)" in source
    assert "def _resume_paused_batch" in source
    assert 'text="暂停", width=' not in source
    assert "SimpleQueue" in source
    assert "self.pending_download_snapshots[snapshot.spec.task_id] = snapshot" in source
    assert "def _drain_ui_events" in source


def test_cached_install_uses_a_visible_non_interactive_primary_state() -> None:
    source = APP_ENTRY.read_text(encoding="utf-8")
    state_method = source.split("def _set_batch_download_state", 1)[1].split(
        "def _cancel_all_downloads", 1
    )[0]
    schedule_method = source.split("def _schedule_ready_installs", 1)[1].split(
        "def _cache_integrity_failure", 1
    )[0]
    done_method = source.split("def _on_auto_install_worker_done", 1)[1].split(
        "def _maybe_finish_unlock_workflow", 1
    )[0]

    assert '"installing": ("正在安装…", False)' in state_method
    assert 'self._set_batch_download_state("installing")' in schedule_method
    assert "发现 {len(jobs)} 个已下载缓存" in schedule_method
    assert 'self.batch_download_state == "installing"' in done_method
    assert 'self._set_batch_download_state("idle")' in done_method
    assert "InstallAccessError" in source
    assert "InstallConflictError" in source
    assert "Automatic DLC installation blocked" in schedule_method


def test_ready_cache_requires_explicit_session_install_intent() -> None:
    source = APP_ENTRY.read_text(encoding="utf-8")
    schedule_method = source.split("def _schedule_ready_installs", 1)[1].split(
        "def _on_auto_install_progress", 1
    )[0]
    batch_method = source.split("def _start_dlc_batch", 1)[1].split(
        "def _set_batch_download_state", 1
    )[0]
    restore_method = source.split("def _restore_original_state", 1)[1].split(
        "def _on_original_state_restored", 1
    )[0]

    assert "self.auto_install_requested_task_ids = set()" in source
    assert "task_id not in self.auto_install_requested_task_ids" in schedule_method
    assert "self.auto_install_requested_task_ids.add(task_id)" in batch_method
    assert "self.auto_install_requested_task_ids.clear()" in restore_method
    assert source.count("self.auto_install_requested_task_ids.discard(") >= 5
    assert "self.auto_install_requested_task_ids.discard(" in source.split(
        "def _on_auto_install_success", 1
    )[1].split("def _on_auto_install_failure", 1)[0]


def test_ready_cache_without_current_intent_does_not_start_installer() -> None:
    from signriver_app.domain import DownloadState

    schedule = _app_method("_schedule_ready_installs")
    schedule.__globals__["DownloadState"] = DownloadState
    task_id = "test-dlc001"
    snapshot = SimpleNamespace(
        spec=SimpleNamespace(task_id=task_id),
        state=DownloadState.READY,
        result_path=Path("cached.zip"),
        sha256="a" * 64,
    )
    queue = SimpleNamespace(snapshots=lambda: (snapshot,))
    entry = SimpleNamespace(dlc_id="dlc001")
    app = SimpleNamespace(
        auto_install_worker_running=False,
        install_recovery_running=False,
        install_recovery_failed=False,
        install_service=object(),
        current_installation=SimpleNamespace(root=Path("game")),
        download_queue=queue,
        cartridge=SimpleNamespace(
            adapter=SimpleNamespace(
                inspect=lambda _installation: SimpleNamespace(running=False)
            ),
            cartridge_id="test",
        ),
        context=SimpleNamespace(logger=SimpleNamespace(exception=lambda *_args: None)),
        catalog_entries=(entry,),
        auto_install_requested_task_ids=set(),
        auto_install_attempted=set(),
        _dlc_task_id=lambda dlc_id: f"test-{dlc_id}",
        _is_entry_installed=lambda _entry: False,
    )

    schedule(app)

    assert app.auto_install_worker_running is False
    assert app.auto_install_attempted == set()


def test_cached_install_reports_item_progress_and_recovers_interrupted_work() -> None:
    source = APP_ENTRY.read_text(encoding="utf-8")
    schedule_method = source.split("def _schedule_ready_installs", 1)[1].split(
        "@staticmethod", 1
    )[0]
    recovery_method = source.split("def _recover_incomplete_installs", 1)[1].split(
        "def _show_game_error", 1
    )[0]

    assert "enumerate(jobs, start=1)" in schedule_method
    assert "def _on_auto_install_progress" in schedule_method
    assert 'text=f"安装中 {index}/{total}…"' in schedule_method
    assert "service.recover_incomplete((game_root,))" in recovery_method
    assert 'name="install-transaction-recovery"' in recovery_method
    assert "self.install_recovery_pending" in recovery_method


def test_advanced_catalog_uses_one_lightweight_receipt_lookup() -> None:
    source = APP_ENTRY.read_text(encoding="utf-8")
    render_method = source.split("def _render_catalog_rows", 1)[1].split(
        "def _render_catalog_batch", 1
    )[0]
    state_method = source.split("def _show_install_state", 1)[1].split(
        "def _manage_entry", 1
    )[0]

    assert "self._refresh_active_receipt_dlc_ids()" in render_method
    assert "active_dlc_ids(" in source
    assert "has_receipt =" in state_method
    assert "self._active_receipt(" not in state_method
    assert "snapshots.get(task_id)" in source


def test_cache_analysis_and_cleanup_do_not_block_tk_thread() -> None:
    source = APP_ENTRY.read_text(encoding="utf-8")
    cleanup_method = source.split("def _cleanup_cache", 1)[1].split(
        "def _run_speed_test", 1
    )[0]

    assert 'name="cache-maintenance-preview"' in cleanup_method
    assert 'name="cache-maintenance-execute"' in cleanup_method
    assert "preview_install_maintenance" in cleanup_method
    assert "execute_install_maintenance" in cleanup_method
    assert "self._post_ui(" in cleanup_method
    assert "活动事务及其备份不会删除" in cleanup_method


def test_client_refuses_to_close_during_destructive_background_work() -> None:
    source = APP_ENTRY.read_text(encoding="utf-8")
    close_method = source.split("def _close", 1)[1].split(
        "def _show_download_state", 1
    )[0]

    assert "self._content_work_is_active()" in close_method
    assert "self.cache_cleanup_running" in close_method
    assert "任务仍在进行" in close_method
    assert close_method.index("return") < close_method.index("self.window.destroy()")


def test_bulk_uninstall_selects_every_absent_catalog_entry_for_reinstall() -> None:
    source = APP_ENTRY.read_text(encoding="utf-8")
    finish_method = source.split("def _finish_dlc_removal", 1)[1].split(
        "# ---- Patch workflow", 1
    )[0]

    assert 'title == "卸载全部 DLC"' in finish_method
    assert "self.selected_dlc_ids = {" in finish_method
    assert "if not self._is_entry_installed(entry)" in finish_method
    assert "self.catalog_selection_initialized = True" in finish_method
    assert "已自动全选可重新安装的 DLC" in finish_method


def test_download_task_rows_are_compact_and_do_not_create_empty_action_frames() -> None:
    source = APP_ENTRY.read_text(encoding="utf-8")

    assert 'border_width=1, border_color=UI["border"], height=68' in source
    assert "def _render_task_row_actions" in source
    assert "if not active and snapshot.state not in" in source
    assert "self.task_action_keys.get(task_id) == action_key" in source
    assert 'row.pack_propagate(False)' in source


def test_download_task_progress_updates_in_place_until_row_controls_change() -> None:
    source = APP_ENTRY.read_text(encoding="utf-8")
    event_method = source.split("def _apply_download_event", 1)[1].split(
        "def _show_recovered_downloads", 1
    )[0]
    update_method = source.split("def _update_task_page_snapshot", 1)[1].split(
        "def _schedule_task_refresh", 1
    )[0]
    row_update_method = source.split("def _update_task_row_snapshot", 1)[1].split(
        "def _active_download_task_id", 1
    )[0]

    assert "self.task_status_labels" in source
    assert "self.task_row_states" in source
    assert "self._update_task_page_snapshot(snapshot)" in event_method
    assert "self._schedule_task_refresh()" not in event_method
    assert "self._update_task_row_snapshot(snapshot)" in update_method
    assert "label.configure(text=self._task_status_text(snapshot))" in row_update_method
    assert "DownloadState.READY" in update_method
    # A full rebuild is now only the fallback for a genuinely new/missing row.
    assert "self._schedule_task_refresh()" in update_method


def test_download_task_page_reuses_cancel_all_and_tracks_active_row() -> None:
    source = APP_ENTRY.read_text(encoding="utf-8")
    refresh_method = source.split("def _refresh_task_page", 1)[1].split(
        "def _task_status_text", 1
    )[0]

    assert 'text="取消全部下载"' in source
    assert source.count("command=self._cancel_all_downloads") == 2
    assert "def _active_download_task_id" in refresh_method
    assert "DownloadState.DOWNLOADING" in refresh_method
    assert "DownloadState.QUEUED" not in source.split(
        "def _active_download_task_id", 1
    )[1].split("def _reset_task_scroll", 1)[0]
    assert "self.task_rows[snapshot.spec.task_id] = row" in refresh_method
    assert "self._schedule_task_scroll(active_task_id)" in refresh_method
    assert "canvas.yview_moveto(0.0)" in refresh_method


def test_original_restore_keeps_cache_without_secondary_prompt() -> None:
    source = APP_ENTRY.read_text(encoding="utf-8")
    restore_method = source.split("def _restore_original_state", 1)[1].split(
        "def _on_original_restore_failed", 1
    )[0]

    assert '"缓存处理"' not in restore_method
    assert "delete_cached_packages=True" not in restore_method
    assert "clear_cache" not in restore_method
    assert 'cache_detail = "下载缓存已保留"' in restore_method


def test_downloads_are_fixed_to_single_threaded_sequential_mode() -> None:
    source = APP_ENTRY.read_text(encoding="utf-8")

    assert 'max_concurrent=1' in source
    assert 'download_concurrency=1' in source
    assert "self.concurrency_menu" not in source
    assert '"；任务将按列表顺序逐个下载"' in source


def test_ready_cache_is_restored_installed_items_are_grey_and_batch_can_cancel() -> None:
    source = APP_ENTRY.read_text(encoding="utf-8")

    assert "def _reconcile_catalog_cache" in source
    assert "queue.reconcile_cached(" in source
    assert "verifier_for=verifier_for" in source
    assert "self.cache_reconcile_running" in source
    assert "self.cache_reconcile_pending" in source
    assert "specs.extend(self._patch_download_specs())" not in source
    assert "def _installed_dlc_path" in source


def test_cache_reconcile_stale_generation_is_silent_and_runs_latest_pending() -> None:
    finish = _app_method("_finish_cache_reconcile")

    class Cartridge:
        cartridge_id = "new-cartridge"

    class Application:
        game_selection_generation = 8
        cartridge = Cartridge()
        cache_reconcile_lock = __import__("threading").Lock()
        cache_reconcile_running = True
        cache_reconcile_active_key = "old-key"
        cache_reconcile_pending = ("new-request",)

        def __init__(self) -> None:
            self.notices = []
            self.started = []

        def _on_cache_reconciled(self, *args, **kwargs) -> None:
            self.notices.append((args, kwargs))

        def _start_cache_reconcile(self, request) -> None:
            self.started.append(request)

    application = Application()
    old_request = ("old-key", 7, "old-cartridge", (), None)
    finish(
        application,
        old_request,
        4,
        generation=7,
        cartridge_id="old-cartridge",
    )

    assert application.notices == []
    assert application.started == [("new-request",)]
    assert application.cache_reconcile_running is True
    assert application.cache_reconcile_active_key == "new-request"
    assert application.cache_reconcile_pending is None


def test_cache_reconcile_latest_request_can_cancel_stale_pending_scan() -> None:
    source = APP_ENTRY.read_text(encoding="utf-8")
    method = source.split("def _reconcile_catalog_cache", 1)[1].split(
        "def _start_cache_reconcile", 1
    )[0]

    assert "if self.cache_reconcile_active_key != request_key:" in method
    assert "else:\n                    # A -> B -> A" in method
    assert "self.cache_reconcile_pending = None" in method


def test_manual_dlc_operations_share_the_global_file_operation_gate() -> None:
    source = APP_ENTRY.read_text(encoding="utf-8")
    begin = source.split("def _begin_manual_file_operation", 1)[1].split(
        "def _manual_file_operation_is_current", 1
    )[0]
    require = source.split("def _require_game_stopped", 1)[1].split(
        "def _launch_game", 1
    )[0]

    for marker in (
        "self.auto_install_worker_running",
        "self.cache_cleanup_running",
        'self.batch_download_state != "idle"',
        'self.patch_workflow_state != "idle"',
    ):
        assert marker in begin
        assert marker in require


def test_game_switch_and_missing_install_clear_previous_install_state() -> None:
    source = APP_ENTRY.read_text(encoding="utf-8")
    select = source.split("def _select_game", 1)[1].split(
        "def _content_work_is_active", 1
    )[0]
    scanned = source.split("def _on_game_scanned", 1)[1].split(
        "def _choose_game_path", 1
    )[0]

    for method in (select, scanned):
        assert "self.installed_dlc_paths = {}" in method
        assert "self.active_receipt_dlc_ids = frozenset()" in method
        assert "self.install_recovery_failed = False" in method


def test_partial_cache_cleanup_always_rescans_cache_and_ready_records() -> None:
    source = APP_ENTRY.read_text(encoding="utf-8")
    worker = source.split("def _confirm_cache_cleanup", 1)[1].split(
        "def _finish_cache_cleanup", 1
    )[0]
    failed = source.split("def _finish_cache_cleanup_error", 1)[1].split(
        "def _run_speed_test", 1
    )[0]

    assert "finally:" in worker
    assert "invalidate_hashes(fresh_plan.paths)" in worker
    assert "self._schedule_cache_usage_scan(force=True)" in failed
    assert "self._reconcile_catalog_cache()" in failed


def test_one_click_unlock_flow_is_wired_to_patch_engine() -> None:
    """The unlock button drives a patch phase followed by the DLC batch."""
    source = APP_ENTRY.read_text(encoding="utf-8")

    assert 'command=self._one_click_unlock' in source
    assert "def _one_click_unlock" in source
    assert "def _start_unlock_workflow" in source
    assert "def _start_patch_downloads" in source
    assert "def _apply_patch_after_download" in source
    assert "def _on_patch_applied" in source
    assert "def _on_patch_workflow_failed" in source
    assert 'self.patch_workflow_state = "downloading"' in source
    assert 'self._set_batch_download_state("patch_downloading")' in source
    assert 'self._set_batch_download_state("patch_applying")' in source
    # Patch tasks flow through the same DownloadQueue as DLC packages, using
    # dedicated task IDs so the UI can route their completion callbacks.
    assert "dict(self.cartridge.patch_task_roles(snapshot.patch_bundle))" in source
    assert "for task_id, role in self.patch_task_roles.items()" in source
    # Once the patch is applied the workflow hands off to the DLC batch code
    # that was already tested in earlier releases.
    assert "self._start_dlc_batch(selected_entries)" in source
    assert "def _maybe_finish_unlock_workflow" in source
    assert 'messagebox.showinfo("一键解锁成功"' in source
    assert "self.unlock_workflow_active" in source
    finish_method = source.split("def _maybe_finish_unlock_workflow", 1)[1].split(
        "def _show_install_state", 1
    )[0]
    assert "self.patch_engine.audit_recorded" in finish_method
    assert "DLC 已安装，但补丁复检失败" in finish_method
    assert 'messagebox.showwarning(' in finish_method


def test_patch_download_does_not_treat_gitlink_display_size_as_exact() -> None:
    source = APP_ENTRY.read_text(encoding="utf-8")
    method = source.split("def _download_spec_for_patch", 1)[1].split(
        "def _patch_asset_for", 1
    )[0]

    assert "expected_size=None" in method
    assert "expected_size=asset.size_bytes" not in method


def test_patch_workflow_detects_security_software_quarantine() -> None:
    source = APP_ENTRY.read_text(encoding="utf-8")

    assert "def _missing_ready_patch_asset" in source
    assert "def _patch_security_software_message" in source
    assert "Windows 安全中心或其他杀毒软件隔离" in source
    assert "self.download_queue.forget((spec.task_id,))" in source
    assert "Post-apply patch audit failed" in source
    assert "self.patch_engine.restore_original" in source


def test_patch_health_uses_recorded_content_hashes() -> None:
    source = APP_ENTRY.read_text(encoding="utf-8")
    method = source.split("def _patch_is_healthy", 1)[1].split(
        "def _start_patch_downloads", 1
    )[0]

    assert "audit_recorded" in method
    assert "size_bytes" not in method


def test_catalog_assigns_entries_before_scanning_slug_based_installs() -> None:
    source = APP_ENTRY.read_text(encoding="utf-8")
    method = source.split("def _show_catalog(", 1)[1].split(
        "def _show_catalog_error", 1
    )[0]

    assign = method.index("self.catalog_entries = entries")
    scan = method.index("self._refresh_installed_dlc_paths()")
    assert assign < scan


def test_repair_button_wipes_dlc_and_patch_and_requires_confirmation() -> None:
    source = APP_ENTRY.read_text(encoding="utf-8")

    assert 'command=self._one_click_repair' in source
    assert "def _one_click_repair" in source
    assert 'self._set_batch_download_state("repairing")' in source
    assert "优先复用已校验缓存，缓存缺失时才重新下载" in source
    assert "patch_engine.reset(game_root)" in source
    repair_method = source.split("def _one_click_repair", 1)[1].split(
        "def _continue_repair_after_patch", 1
    )[0]
    assert "delete_cached_packages=True" not in repair_method
    assert "self.auto_install_attempted.discard" in repair_method
    assert "def _continue_repair_after_patch" in source


def test_download_and_install_form_a_single_worker_pipeline_without_duplicate_install() -> None:
    source = APP_ENTRY.read_text(encoding="utf-8")
    finished = source.split("def _download_finished", 1)[1].split(
        "def _queue_download_event", 1
    )[0]
    installer = source.split("def _schedule_ready_installs", 1)[1].split(
        "def _on_auto_install_success", 1
    )[0]

    assert "install_service.install" not in finished
    assert "service.install(" in installer
    assert 'name="dlc-installer"' in installer
    assert "self.auto_install_worker_running" in installer
    assert "known_sha256=actual_sha256" in source
    assert "def _retry_invalid_cached_package" in source
    assert "self.download_queue.invalidate_cached" in source


def test_remove_patch_button_uses_real_engine_instead_of_placeholder() -> None:
    source = APP_ENTRY.read_text(encoding="utf-8")

    assert 'command=self._remove_patch' in source
    assert "def _remove_patch" in source
    assert "engine.restore_original(game_root)" in source
    assert "OriginalStateRestoreService(" in source
    assert "RestoreScope" not in source
    assert "彻底恢复" not in source
    assert "游戏原有 DLC 和其他来源的内容不会被删除" in source
    # The old placeholder message must be gone entirely so users never see the
    # "按钮已预留" copy after an update.
    assert "按钮已预留" not in source
    assert "_show_patch_removal_placeholder" not in source
