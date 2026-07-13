from __future__ import annotations

import ast
from pathlib import Path


APP_ENTRY = Path(__file__).parents[1] / "app" / "versions" / "0.1.0" / "app_entry.py"


def _ui_palette() -> dict[str, str]:
    module = ast.parse(APP_ENTRY.read_text(encoding="utf-8"))
    assignment = next(
        node for node in module.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "UI" for target in node.targets)
    )
    return ast.literal_eval(assignment.value)


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


def test_all_dropdowns_use_bordered_combo_box_factory() -> None:
    source = APP_ENTRY.read_text(encoding="utf-8")

    assert "CTkOptionMenu(" not in source
    assert source.count("= _combo_box(") == 3
    assert '"border_width": 1' in source
    assert 'self.catalog_filter.set("全部状态")' in source
    assert 'self.log_level_filter.set("全部")' in source


def test_catalog_defaults_to_simple_view_with_advanced_management() -> None:
    source = APP_ENTRY.read_text(encoding="utf-8")

    assert 'self.catalog_view_mode = "simple"' in source
    assert 'text="高级管理"' in source
    assert 'text="一键下载所选"' in source
    assert "def _render_simple_catalog_rows" in source
    assert "def _render_advanced_catalog_rows" in source
    assert "def _simple_entry_status" in source


def test_catalog_view_toggle_resets_scroll_after_rebuilding_rows() -> None:
    source = APP_ENTRY.read_text(encoding="utf-8")

    assert "def _reset_catalog_scroll" in source
    assert 'canvas.configure(scrollregion=canvas.bbox("all"))' in source
    assert "canvas.yview_moveto(0.0)" in source
    assert "def _schedule_catalog_scroll_reset" in source
    assert "self._schedule_catalog_scroll_reset()" in source


def test_simple_catalog_is_compact_and_has_complete_bulk_selection() -> None:
    source = APP_ENTRY.read_text(encoding="utf-8")

    assert "self.simple_catalog_columns = 5" in source
    assert "columns = 4 if compact else 5" in source
    assert "self.catalog_selection_initialized = False" in source
    assert "if entries and not self.catalog_selection_initialized:" in source
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
    assert 'text="测试下载速度"' in source
    assert "measure_download_speed(url)" in source
    assert "releases/download/test/test.bin" in source
    assert 'text="一键移除补丁"' in source
    assert 'text="卸载全部 DLC"' in source
    assert "def _uninstall_all_dlc" in source
    assert "remove_installed_dlc(game_root, dlc_id)" in source
    assert "uninstall.configure(state=\"normal\")" in source


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


def test_download_task_rows_are_compact_and_do_not_create_empty_action_frames() -> None:
    source = APP_ENTRY.read_text(encoding="utf-8")

    assert 'border_width=1, border_color=UI["border"], height=68' in source
    assert 'if active or snapshot.state in {DownloadState.PAUSED, DownloadState.FAILED}:' in source
    assert 'row.pack_propagate(False)' in source


def test_downloads_are_fixed_to_single_threaded_sequential_mode() -> None:
    source = APP_ENTRY.read_text(encoding="utf-8")

    assert 'max_concurrent=1' in source
    assert 'text="单线程顺序下载（固定）"' in source
    assert 'download_concurrency=1' in source
    assert "self.concurrency_menu" not in source
    assert '"；任务将按列表顺序逐个下载"' in source


def test_ready_cache_is_restored_installed_items_are_grey_and_batch_can_cancel() -> None:
    source = APP_ENTRY.read_text(encoding="utf-8")

    assert "def _reconcile_catalog_cache" in source
    assert "self.download_queue.reconcile_cached(specs)" in source
    assert "def _installed_dlc_path" in source
    assert 'fg_color=UI["panel"] if installed else UI["card"]' in source
    assert 'state="disabled" if installed else "normal"' in source
    assert "def _schedule_ready_installs" in source
    assert "包结构和 DLC 编号校验通过后自动安装到当前游戏目录" in source
    assert "安装保持禁用" not in source
    assert 'text="取消全部下载"' in source
    assert "self.download_queue.cancel_many(unfinished)" in source
    assert 'text="全部未完成下载已取消；已清空选择，可以重新勾选需要的 DLC"' in source
