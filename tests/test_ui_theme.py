from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace


# These assertions describe the CURRENT UI implementation. Git only tracks
# app/versions/0.1.0 as module source; later version directories are restored
# from release archives on CI and may be stale, so always read 0.1.0 here.
APP_ENTRY = Path(__file__).parents[1] / "app" / "versions" / "0.1.0" / "app_entry.py"
CURRENT_APP_ENTRY = APP_ENTRY
LAUNCHER_MAIN = Path(__file__).parents[1] / "src" / "signriver_launcher" / "main.py"
GUIDES_ROOT = Path(__file__).parents[1] / "config" / "guides"


def test_current_update_ui_surfaces_version_cancel_and_transient_task() -> None:
    source = CURRENT_APP_ENTRY.read_text(encoding="utf-8")

    assert 'text="取消下载"' in source
    assert "self.context.app_version" in source
    assert "def _cancel_update_download" in source
    assert "def _render_update_download_row" in source


def test_user_ui_hides_internal_diagnostics() -> None:
    source = APP_ENTRY.read_text(encoding="utf-8")
    launcher = LAUNCHER_MAIN.read_text(encoding="utf-8")

    assert "扫描产生" not in source
    assert " · App {" not in source
    assert "开发调试时可开启" not in source
    assert "启动失败时保留当前模块" in source
    assert "技术详情 / Traceback" not in source
    assert "云端资源" in source
    # Fatal dialog stays concise; the detailed formatter remains available for
    # the explicit copy-diagnostics action and logs.
    fatal_dialog = launcher.split("def _show_fatal_error", 1)[1].split(
        "def _format_fatal_error_details", 1
    )[0]
    assert "错误码" not in fatal_dialog
    assert "事件 ID" not in fatal_dialog
    assert "def _format_fatal_error_details" in launcher


def test_game_picker_keeps_long_names_left_aligned_and_wrapped() -> None:
    source = APP_ENTRY.read_text(encoding="utf-8")
    picker = source.split("def _refresh_game_picker_results", 1)[1].split(
        "def _choose_game_from_picker", 1
    )[0]

    assert 'anchor="w"' in picker
    assert 'justify="left"' in picker
    assert "wraplength=350" in picker


def test_guides_request_user_friendly_evidence() -> None:
    guide_text = "\n".join(path.read_text(encoding="utf-8") for path in GUIDES_ROOT.glob("*.json"))

    assert "错误详情或诊断信息" not in guide_text
    assert "说明遇到的现象，必要时附上截图" in guide_text
PUBLISHER_ROOT = Path(__file__).parents[1] / "src" / "signriver_publisher"
PUBLISHER_UI = PUBLISHER_ROOT / "ui.py"
PUBLISHER_UI_SOURCES = tuple(
    PUBLISHER_ROOT / name
    for name in (
        "ui.py",
        "ui_runtime.py",
        "content_management_ui.py",
        "remote_maintenance_ui.py",
    )
)


def _publisher_source() -> str:
    return "\n".join(path.read_text(encoding="utf-8") for path in PUBLISHER_UI_SOURCES)


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


def _app_method_source(name: str) -> str:
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
    return ast.get_source_segment(APP_ENTRY.read_text(encoding="utf-8"), method) or ""


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
    assert 'self.sidebar.configure(width=164 if compact else 188)' in source


def test_game_selector_uses_a_searchable_in_app_picker_and_home_uses_github() -> None:
    source = APP_ENTRY.read_text(encoding="utf-8")

    assert 'self.game_selector = _combo_box(' in source
    assert 'def _open_game_picker_from_combo' in source
    assert '"right_parts", "<Button-1>", self._open_game_picker_from_combo' in source
    assert '"dropdown_arrow", "<Button-1>", self._open_game_picker_from_combo' in source
    assert '"border_color": UI["input_border"]' in source
    assert 'def _show_game_picker' in source
    assert 'ctk.CTkToplevel(self.window)' in source
    assert 'ctk.CTkEntry(' in source
    assert 'ctk.CTkScrollableFrame(' in source
    assert 'game.get("display_name", "")' in source
    assert 'game.get("game_id", "")' in source
    assert '✓ 当前选择' in source
    assert 'f"{display_name}  ·  ✓ 当前选择"' in source
    assert 'height=54 if is_current or len(display_name) > 24 else 40' in source
    assert '没有找到匹配的游戏' in source
    assert 'self._set_game_selector_text(display_name)' in source
    assert 'text="复制游戏列表"' in source
    assert 'fg_color="transparent"' in source
    assert 'https://github.com/sign-river/SignRiver-DLC-Hub' in source
    assert '"github.com", "space.bilibili.com"' in source


def test_active_cartridge_switch_always_updates_the_visible_game_selector() -> None:
    source = _app_method_source("_apply_selected_cartridge")

    assert "self.selected_game_name = display_name" in source
    assert "self._set_game_selector_text(display_name)" in source


def test_error_guide_is_the_single_sidebar_entry_for_logs_and_problem_records() -> None:
    source = APP_ENTRY.read_text(encoding="utf-8")

    assert 'for page_name in ("DLC 库", "下载任务", "报错指南", "设置")' in source
    assert '"报错指南": (self.error_guide_card,)' in source
    assert '"问题记录": (self.problem_card,)' in source
    assert '"运行日志": (self.log_card,)' in source
    assert '("问题记录", "查看已记录的异常与处理建议", "问题记录")' in source
    assert 'text="帮助与诊断"' in source
    assert 'text="开始一键排错  →"' in source
    assert "_quick_check_recent_problems" not in source
    assert '"近期异常："' not in source
    assert '("解决方案", "按现象查看对应的处理办法", "常见问题教程")' in source
    assert '("运行日志", "查看详细运行信息", "运行日志")' in source
    assert 'text="返回指南"' in source
    assert 'text=f"当前平台可用 {len(self.supported_games)} 款游戏"' in source
    assert 'f"已同步 {len(self.supported_games)} 款游戏"' in source
    assert '已同步游戏主表（' not in source
    problem_layout = source.split('problem_header = ctk.CTkFrame(self.problem_card', 1)[1].split(
        'problem_body = ctk.CTkFrame(', 1
    )[0]
    assert problem_layout.index('text="返回指南"') < problem_layout.index(
        'text="刷新"'
    ) < problem_layout.index('text="清空全部记录"')
    assert 'guide_footer.pack(side="bottom", fill="x", padx=36, pady=(0, 24))' in source
    assert 'guide_actions = ctk.CTkScrollableFrame(' in source
    assert 'guide_actions.pack(fill="both", expand=True, padx=36, pady=(0, 12))' in source
    assert 'self.solution_back_button' not in source
    assert 'def _return_to_guide_from_solution_list' not in source
    assert 'self.solution_detail_back_button = ctk.CTkButton(' in source
    assert 'command=lambda: self._show_page("报错指南")' in source
    assert 'self.solution_detail_back_button.configure(command=self._return_from_solution_detail)' in source
    assert 'text="← 回到一键排错"' in source
    assert 'text="← 返回解决方案"' in source
    assert 'text="可以关闭 Windows Defender"' in source
    assert 'text="查看教程"' in source
    solution_detail = source.split("def _show_solution_detail", 1)[1].split("def _show_solution_list", 1)[0]
    assert "_pack_helper_tool_actions" not in solution_detail
    assert "工具管理统一在工具详情页完成" in solution_detail
    assert 'target.startswith("tool:")' in source
    assert 'return "下载工具"' in source
    assert 'return "暂停下载"' in source
    assert 'return "删除下载"' in source
    assert 'else "启动工具"' in source
    assert 'text="← 返回杀毒软件检测"' in source
    assert 'origin="security_products"' in source
    log_layout = source.split('self.log_card = _card(self.page_host)', 1)[1].split(
        'self.log_preview = ctk.CTkTextbox(', 1
    )[0]
    assert 'text="返回指南", width=92' in log_layout
    assert ').grid(row=0, column=1, sticky="e")' in log_layout
    assert 'border_color=UI["border"], corner_radius=10' in log_layout
    assert 'log_tools.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(14, 0))' in log_layout
    assert 'log_action_grid.grid(row=0, column=3, sticky="e"' in log_layout


def test_top_brand_area_warns_that_the_app_is_free_and_open_source() -> None:
    source = APP_ENTRY.read_text(encoding="utf-8")

    assert '开源免费 · 付费购买请立即退款"' in source
    assert 'self.top_health.grid(row=0, column=0, sticky="w", padx=(0, 18))' in source
    assert "PRODUCT_TITLE_ZH" in source
    assert 'self.window.title(PRODUCT_TITLE_ZH)' in source
    assert 'PRODUCT_HEADER_TITLE_ZH = "DLC一键解锁工具"' in source
    assert 'text=PRODUCT_HEADER_TITLE_ZH' in source
    assert 'text=f"{AUTHOR_CN}|{AUTHOR_EN}  ·  开源免费 · 付费购买请立即退款"' in source
    assert 'AUTHOR_CN = "唏嘘南溪"' in source
    assert 'USAGE_TUTORIAL_URL = "https://sign-river.github.io/p/signriver-dlc-hub/getting-started/"' in source
    assert "BILIBILI_TUTORIAL_URL" in source
    assert "messagebox.askyesnocancel(" in source
    assert 'profile_group, text="使用教程", width=78,' in source
    assert 'command=self._open_usage_tutorial' in source
    assert 'text="打开当前下载源的资源仓库"' in source
    assert 'self.resource_repository_link = ctk.CTkLabel(' in source
    assert 'text="唏嘘南溪"' in source
    assert 'text="DLC一键解锁工具"' in source
    assert "def _apply_window_icon" in source
    assert "SetCurrentProcessExplicitAppUserModelID" in source
    assert "def _apply_native_windows_icons" in source
    assert "def _content_wraplength_for" in source
    assert "def _sync_help_wraplengths" in source
    assert "iconphoto(" not in source
    assert "app.ico" in source


def test_tool_center_uses_detail_pages_and_only_declared_tools_in_quick_check() -> None:
    source = APP_ENTRY.read_text(encoding="utf-8")

    assert 'def _show_guide_tool_detail(self, tool: GuideTool)' in source
    assert 'text="' + ''.join(chr(code) for code in (0x67e5, 0x770b, 0x8be6, 0x60c5)) in source
    assert 'def _guide_tools_for_current_platform' in source
    assert 'if tool.quick_check' in source
    assert 'self._quick_check_declared_tool(selected_tool)' in source
    assert 'self.quick_check_waiting' in source
    assert 'def _run_guide_tool_capture' in source
    assert 'capture_output=True' in source
    assert 'def _quick_check_security_products' in source
    assert 'def _replace_quick_check_result' in source
    assert 'text="查看工具详情 →"' in source
    assert 'def _open_security_products_from_quick_check' in source
    assert 'def _open_guide_tool_detail_from_quick_check' in source
    assert 'text="打开文件"' in source
    assert 'def _open_file(self, path: Path)' in source
    assert 'is_windows_security_product(product)' in source
    assert 'is_lenovo_security_product(product)' in source
    assert 'preferred_security_product_executable(product)' in source
    assert 'webbrowser.open(WINDOWS_SECURITY_URI)' in source
    assert 'self.tool_center_detail_page = ctk.CTkFrame(' in source
    assert 'text="← 返回常用工具"' in source
    assert 'def _show_tool_center_detail(self, title: str)' in source
    detail_header = source.split('def _show_tool_center_detail(', 1)[1].split(
        'def _tool_center_column_count', 1
    )[0]
    assert 'self.tool_center_detail_back_button.configure(' in detail_header
    assert 'text=back_text,' in detail_header
    assert 'command=back_command or self._show_tool_center_list,' in detail_header
    assert 'self._solution_return_context: tuple[object, ...] | None = None' in source
    assert 'return_context=(\n                        "guide",' in source
    assert 'if return_context[0] == "guide_tool":' in source
    assert 'if return_context[0] == "patch_tool":' in source
    assert 'source_builtin_tool: str | None = None' in source
    patch_tool = source.split('def _show_patch_tool', 1)[1].split(
        'def _redownload_patch_assets', 1
    )[0]
    assert 'text="打开游戏内补丁安装目录"' in patch_tool
    assert 'text="打开软件内补丁缓存"' in patch_tool
    assert 'text="刷新补丁列表"' in patch_tool
    assert "command=self._refresh_patch_tool" in patch_tool
    assert 'text="打开游戏目录"' not in patch_tool
    assert 'resolve_game_directory(' in patch_tool
    assert 'self.download_manager.cache_root' in patch_tool
    assert 'text="' + ''.join(chr(code) for code in (0x8865, 0x4e01, 0x6587, 0x4ef6)) + '"' in patch_tool
    assert 'issue = "' + ''.join(chr(code) for code in (0x8865, 0x4e01, 0x7f3a, 0x5931, 0xff1a, 0x5c1a, 0x672a, 0x4e0b, 0x8f7d)) + '"' in patch_tool
    assert 'issue = "' + ''.join(chr(code) for code in (0x8865, 0x4e01, 0x7f3a, 0x5931, 0xff1a, 0x7f13, 0x5b58, 0x6587, 0x4ef6, 0x4e0d, 0x53ef, 0x7528)) + '"' in patch_tool
    assert 'if is_ready:' in patch_tool
    assert 'text="' + ''.join(chr(code) for code in (0x8865, 0x4e01, 0x6b63, 0x5e38)) + '"' in patch_tool
    assert 'text_color=UI["success"]' in patch_tool
    assert 'if self._is_file_openable(path):' in patch_tool
    assert 'def _is_file_openable(path: Path) -> bool' in source
    assert 'library_suffixes = (".dll", ".dylib", ".so", ".bundle", ".a", ".lib")' in source
    assert 'dialog = ctk.CTkToplevel(self.window)' not in source.split('def _show_patch_tool', 1)[1].split('def _redownload_patch_assets', 1)[0]
    assert 'dialog = ctk.CTkToplevel(self.window)' not in source.split('def _render_security_products', 1)[1].split('def _open_security_product', 1)[0]


def test_tool_center_uses_adaptive_cards_with_visible_descriptions() -> None:
    source = APP_ENTRY.read_text(encoding="utf-8")

    assert 'self.tool_center_list.bind(' in source
    assert '"<Configure>", self._on_tool_center_resize' in source
    assert 'def _tool_center_column_count(self, width: int | None = None)' in source
    assert 'return max(1, min(4, usable_width // 260))' in source
    assert 'def _create_tool_center_card(' in source
    assert 'height=164' in source
    assert 'card.grid_propagate(False)' in source
    assert 'card.grid_rowconfigure(1, weight=1)' in source
    assert 'TOOL_CARD_DESCRIPTION_MAX_LENGTH = 45' in source
    assert 'def _tool_center_card_description(self, description: str)' in source
    assert 'text=self._tool_center_card_description(description)' in source
    assert 'text_color=UI["text_secondary"]' in source
    assert 'wraplength=236' in source
    assert 'text="' + ''.join(chr(code) for code in (0x67e5, 0x770b, 0x8be6, 0x60c5)) + ' ' + chr(0x2192) + '"' in source
    assert '**BUTTON_SECONDARY' in source
    assert 'def _hide_tool_description_tooltip' not in source
    assert 'CTkToplevel(self.window)' not in source.split(
        'def _create_tool_center_card', 1
    )[1].split('def _refresh_tool_center', 1)[0]
    assert 'tool.description or' in source
    assert 'cards.append((' in source
    assert 'self._create_tool_center_card(' in source
    assert 'row.pack(fill="x", padx=8, pady=6)' not in source.split(
        'def _refresh_tool_center', 1
    )[1].split('def _show_guide_tool_detail', 1)[0]


def test_remote_guide_refresh_replaces_removed_entries_in_memory() -> None:
    source = APP_ENTRY.read_text(encoding="utf-8")

    merge = source.split(
        'def _merge_remote_solution_articles', 1
    )[1].split('def _download_guide_tool', 1)[0]
    assert 'builtin_ids = {' in merge
    assert 'if article_id in builtin_ids' in merge
    assert 'self.solution_articles.update(articles)' in merge

def test_tool_item_ui_spec_documents_the_card_description_limit() -> None:
    spec = Path(__file__).parents[1] / "docs" / "tool-item-ui-spec.md"
    text = spec.read_text(encoding="utf-8")

    assert "不超过 **45 个字符**" in text
    assert "## 后续待补充指标" in text


def test_error_guide_button_hierarchy_uses_primary_secondary_and_danger_styles() -> None:
    source = APP_ENTRY.read_text(encoding="utf-8")
    guide = source.split('self.error_guide_card = _card', 1)[1].split(
        'def _build_log_page', 1
    )[0]
    tutorial = _app_method_source("_build_error_tutorial_page")
    tools = _app_method_source("_build_tool_center_page")
    quick_check = _app_method_source("_build_quick_check_page")
    problem_list = _app_method_source("_show_problem_list")
    problem_detail = _app_method_source("_select_problem")
    log_layout = source.split('self.log_card = _card(self.page_host)', 1)[1].split(
        'self.log_preview = ctk.CTkTextbox(', 1
    )[0]

    assert 'text="导出诊断 →"' in guide
    assert 'command=self._export_diagnostics, **BUTTON_SECONDARY' in guide
    assert 'self.problem_back_button' in guide
    assert 'text="清空全部记录"' in guide
    assert 'command=self._clear_problems, **BUTTON_DANGER' in guide
    assert 'command=self._clear_problems,\n            **BUTTON_DANGER' in problem_list
    assert 'text="删除当前问题记录"' in problem_detail
    assert 'self._delete_current_problem(event_id),\n            **BUTTON_DANGER' in problem_detail
    assert 'self.solution_list_back_button' in tutorial
    assert '**BUTTON_SECONDARY' in tutorial
    assert 'self.tool_center_back_button' in tools
    assert 'self.tool_center_detail_related_button' in tools
    assert quick_check.count('**BUTTON_SECONDARY') >= 3
    assert 'command=self._run_quick_check, **BUTTON_PRIMARY' in quick_check
    assert 'command=self._terminate_quick_check, **BUTTON_DANGER' in quick_check
    assert 'text="复制当前日志"' in log_layout
    assert 'command=self._copy_log, width=116,\n            **BUTTON_PRIMARY' in log_layout


def test_error_guide_details_style_dynamic_actions_by_current_semantics() -> None:
    patch_tool = _app_method_source("_show_patch_tool")
    helper_actions = _app_method_source("_pack_helper_tool_actions")
    helper_style = _app_method_source("_helper_download_button_style")
    problem_actions = _app_method_source("_render_problem_actions")
    quick_results = _app_method_source("_render_quick_check_output")
    tool_detail = _app_method_source("_show_guide_tool_detail")
    security_products = _app_method_source("_render_security_products")
    defender_banner = _app_method_source("_pack_close_windows_defender_banner")
    tool_center = _app_method_source("_build_tool_center_page")
    solution_navigation = _app_method_source("_activate_solution_button")

    assert 'text="从云端重新下载补丁"' in patch_tool
    assert 'command=self._redownload_patch_assets, **BUTTON_PRIMARY' in patch_tool
    assert patch_tool.count('**BUTTON_SECONDARY') >= 5
    assert 'return BUTTON_PRIMARY' in helper_style
    assert 'return BUTTON_SECONDARY' in helper_style
    assert 'return BUTTON_DANGER' in helper_style
    assert '**self._helper_download_button_style(tool)' in helper_actions
    assert 'command=lambda selected=tool: self._launch_helper_tool(selected),' in helper_actions
    assert '**BUTTON_SECONDARY' in helper_actions
    assert 'text="查看工具详情"' not in helper_actions
    assert 'command=lambda: self._remove_guide_tool(target), **BUTTON_DANGER' in tool_detail
    assert 'command=lambda item=product: self._open_security_product(item),' in security_products
    assert '**BUTTON_SECONDARY' in security_products
    assert 'self._set_tool_ready(self.helper_tools.is_installed(tool))' in tool_detail
    assert '"开发者提供的受控工具" if not tool.is_helper_tool() else ""' in tool_detail
    assert 'text="查看教程"' in defender_banner
    assert 'fg_color=UI["card"]' in defender_banner
    assert 'border_color=UI["border"]' in defender_banner
    assert '**BUTTON_PRIMARY' in defender_banner
    assert 'tool_id == "security-products"' in solution_navigation
    assert 'command=self._copy_tool_logs, **CONSOLE_GHOST_BUTTON' in tool_center
    assert 'self.tool_center_console_clear_button = ctk.CTkButton(' in tool_center
    assert 'command=self._clear_tool_logs,' in tool_center
    assert 'fg_color=UI["danger_surface"]' in tool_center
    assert 'border_color=UI["danger"]' in tool_center
    assert 'ProblemAction.RETRY_TASK' in problem_actions
    assert 'ProblemAction.COPY_DETAILS' in problem_actions
    assert 'if action in {' in problem_actions
    assert 'ProblemAction.DELETE' in problem_actions
    assert 'BUTTON_PRIMARY' in problem_actions
    assert 'BUTTON_DANGER' in problem_actions
    assert 'BUTTON_SECONDARY' in problem_actions
    assert quick_results.count('**BUTTON_SECONDARY') == 2


def test_top_brand_actions_keep_their_width_when_game_names_are_long() -> None:
    source = APP_ENTRY.read_text(encoding="utf-8")

    assert 'status_band = ctk.CTkFrame(' in source
    assert 'status_band.grid_columnconfigure(0, weight=1)' in source
    assert 'status_band.grid_propagate(False)' in source
    assert 'profile_group.grid(row=0, column=1, sticky="e"' in source
    assert 'profile_group, text="QQ群 1061299021", width=132, height=42,' in source
    assert 'text=f"{AUTHOR_CN}|{AUTHOR_EN}  ·  开源免费 · 付费购买请立即退款"' in source
    topbar = source.split('profile_group = ctk.CTkFrame(topbar', 1)[1].split(
        'self.page_host =', 1
    )[0]
    assert 'text="资源仓库"' not in topbar
    assert topbar.index('text="GitHub"') < topbar.index('text="B站"')
    assert topbar.index('text="B站"') < topbar.index('text="使用教程"')
    assert topbar.index('text="使用教程"') < topbar.index('text="QQ群 1061299021"')


def test_dropdowns_use_bordered_combo_box_factory() -> None:
    source = APP_ENTRY.read_text(encoding="utf-8")

    assert "CTkOptionMenu(" not in source
    assert source.count("= _combo_box(") == 5
    assert '"border_width": 1' in source
    assert 'self.catalog_filter.set("全部状态")' in source
    assert 'self.solution_search_mode.set("模糊匹配")' in source
    assert "def _solution_matches_search" in source
    assert "offset = source.find(character, offset)" in source
    assert 'self.log_level_filter.set("全部")' in source
    assert '_settings_header(network_card, "下载与网络", "下载源、连接质量与等待策略")' in source
    assert "self.download_source_menu" in source
    assert "speed_test_url(self.user_settings.download_source)" in source
    assert "repository_home_url(self.user_settings.download_source)" in source
    assert "self.context.updates.set_download_source(selected)" in source
    assert (
        "self.context.updates.set_download_source(\n"
        "                self.user_settings.download_source"
    ) in source


def test_game_installation_status_does_not_reference_removed_version_text() -> None:
    source = APP_ENTRY.read_text(encoding="utf-8")

    assert "version_text" not in source
    assert 'text="路径已验证"' in source
    assert 'text="未检测到有效安装"' in source


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


def test_catalog_actions_require_remote_cartridge_sync() -> None:
    source = APP_ENTRY.read_text(encoding="utf-8")

    assert "self.cartridge_remote_synced = False" in source
    assert "allow_fallback=False" in source
    assert "卡带配置未同步，DLC 操作已禁用" in source
    assert 'text="等待卡带同步"' in source
    assert "self.cartridge.adapter.descriptor.game_id" in source


def test_catalog_commands_emphasize_unlock_and_align_secondary_actions() -> None:
    source = APP_ENTRY.read_text(encoding="utf-8")

    assert "catalog_command_bar = ctk.CTkFrame(" in source
    assert 'uniform="catalog-management"' in source
    assert "primary_action_panel = ctk.CTkFrame(" in source
    assert 'width=176,' in source
    assert 'height=44,' in source
    assert 'font=ctk.CTkFont(size=18, weight="bold")' in source
    assert 'widget is getattr(self, "download_selected_button", None)' in source
    assert 'self.download_selected_button.pack(padx=4, pady=3)' in source
    assert 'self.download_selected_button.pack(fill="both", expand=True' not in source
    assert '"primary_surface": "#EAF3FB"' in source
    assert 'getattr(self, "catalog_refresh_button", None)' in source
    assert 'getattr(self, "selection_toggle_button", None)' in source
    assert 'getattr(self, "repair_button", None)' in source


def test_catalog_promotes_repair_and_labels_advanced_actions() -> None:
    source = APP_ENTRY.read_text(encoding="utf-8")

    repair_top = source.index(
        'catalog_secondary_actions, text="一键修复"'
    )
    advanced_menu = source.index(
        'catalog_management_tools,\n            text="逐项管理 DLC"'
    )
    assert repair_top < advanced_menu
    assert 'text="高级操作  ▾"' in source
    assert 'text="收起高级操作  ▴"' in source


def test_log_commands_use_an_aligned_single_row_toolbar() -> None:
    source = APP_ENTRY.read_text(encoding="utf-8")

    assert "log_command_area = ctk.CTkFrame(" in source
    assert "log_action_grid = ctk.CTkFrame(" in source
    assert 'uniform="log-actions"' in source
    assert source.count("log_action_grid, text=") == 4
    assert 'log_tools.grid_columnconfigure(2, weight=1)' in source
    assert 'log_tools, text="筛选"' not in source
    assert 'self.log_search.grid(row=0, column=0, sticky="w", padx=(12, 8), pady=10)' in source
    assert 'log_tools, placeholder_text="输入关键词筛选日志", width=180' in source
    assert 'self.log_level_filter.grid(row=0, column=1, padx=(0, 12), pady=10)' in source
    assert 'log_action_grid.grid(row=0, column=3' in source


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
    assert 'self._show_page("高级DLC视图" if self.catalog_view_mode == "advanced" else "DLC 库")' in toggle_method
    assert "self._show_catalog_view_frame(mode)" in batch_method
    assert "self._render_catalog_rows()" in toggle_method
    assert "batch_size = 12 if mode == \"simple\" else 8" in batch_method
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


def test_page_switch_commits_hidden_and_visible_sections_in_one_draw_pass() -> None:
    source = _app_method_source("_show_page")

    assert "self.page_host.update_idletasks()" not in source
    assert "Geometry changes are committed together" in source
    assert source.index("section.place_forget()") < source.index("sections = self.page_sections[page_name]")


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
    source = _publisher_source()
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
    # Normal empty, built-in-DLC explanatory, and populated resource states
    # all rebuild the scrollable surface.
    assert resources_method.count("self._schedule_scrollable_reset(parent)") == 3
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
    assert 'text="取消全选" if all_selected else "全选 DLC"' in source
    assert "all_selected = bool(selectable)" in source
    assert "self.selection_toggle_button" in source
    assert "self.select_visible_button" not in source
    assert "self.clear_visible_button" not in source
    assert "https://space.bilibili.com/504574253" in source
    assert 'group_number = "1061299021"' in source


def test_bulk_management_speed_test_and_complete_task_cleanup_are_available() -> None:
    source = APP_ENTRY.read_text(encoding="utf-8")
    publisher_source = _publisher_source()

    assert 'text="GitHub"' in source
    assert 'text="清除全部记录"' in source
    assert "self.download_queue.clear_all()" in source
    assert 'self._set_batch_download_state("idle")' in source
    assert "_apply_batch_download_button" not in source
    assert '_settings_header(network_card, "下载与网络", "下载源、连接质量与等待策略")' in source
    assert 'text="开始测速"' in source
    assert "measure_download_speed(url)" in source
    assert "speed_test_url(self.user_settings.download_source)" in source
    assert "已生成静态目录 catalog.json" in publisher_source
    assert 'text="单源发布程序更新"' not in publisher_source
    assert 'text="单源发布模块归档"' not in publisher_source
    content_management_source = (PUBLISHER_ROOT / "content_management_ui.py").read_text(encoding="utf-8")
    release_actions_source = (PUBLISHER_ROOT / "release_actions_ui.py").read_text(encoding="utf-8")
    release_center_ui_source = (PUBLISHER_ROOT / "release_center_ui.py").read_text(encoding="utf-8")
    assert 'command=lambda value=path: self.upload_remote_file(value)' not in content_management_source
    release_center_source = (PUBLISHER_ROOT / "release_center.py").read_text(encoding="utf-8")
    assert "self._open_game_content_release_pipeline()" in release_actions_source
    assert "self.content_release_tab = self.content_tabs.add(\"DLC / 补丁发布\", scrollable=True)" in (PUBLISHER_ROOT / "ui.py").read_text(encoding="utf-8")
    assert "def _build_content_release_tab" in content_management_source
    assert "self.game_menu = ctk.CTkOptionMenu" in content_management_source
    assert "DLC 与补丁资源" not in release_center_source
    assert "open_game_content_pipeline=self._open_game_content_release_pipeline" in release_center_ui_source
    assert "self.workspace.publish_files(profile)" in release_center_ui_source
    assert 'text="一键移除补丁"' in source
    assert 'text="移除本程序安装内容"' in source
    assert 'text="卸载全部 DLC"' not in source
    assert "def _uninstall_all_dlc" not in source
    assert "remove_installed_dlc(game_root, dlc_id)" in source
    assert "uninstall.configure(state=\"normal\")" in source
    assert "符合 dlcNNN_<名称> 规则" not in source


def test_settings_groups_related_controls_into_compact_setting_rows() -> None:
    source = APP_ENTRY.read_text(encoding="utf-8")

    assert '_settings_header(network_card, "下载与网络", "下载源、连接质量与等待策略")' in source
    assert '_settings_header(program_card, "程序与存储", "程序更新、下载缓存与本地空间")' in source
    assert '_settings_header(general_card, "常规设置", "日常提示与后续普通偏好")' in source
    assert "def _settings_group_body" in source
    assert "def _settings_row" in source
    assert "A desktop-style setting row" in source
    assert "self.source_card = network_card" in source
    assert "self.speed_test_card = network_card" in source
    assert "self.resilience_card = network_card" in source
    assert "self.update_card = program_card" in source
    assert "self.cache_card = program_card" in source
    assert "self.announcement_card = general_card" in source
    assert 'text="开始测速"' in source
    assert 'text="检查更新"' in source
    assert 'text="\u6e05\u9664\u6240\u6709\u7f13\u5b58"' in source
    assert "self.download_manager.configure_timeout" in source
    assert "def _refresh_announcement" in source
    assert "def _show_announcement_dialog" in source
    assert "_show_onboarding" not in source
    assert "self.settings_description_boxes" in source
    assert 'justify="left"' in source
    assert "def _blue_switch" in source
    assert "return ctk.CTkSwitch(" in source
    assert 'width=kwargs.pop("width", 154)' in source
    assert 'fg_color="#AEBECD"' in source
    assert 'button_color="#F8FAFC"' in source
    assert 'progress_color=UI["primary"]' in source
    assert "switch_width=44" in source
    assert "self.settings_list" in source
    assert '"设置": (self.settings_list,)' in source
    assert "for index, card in enumerate((network_card, program_card, general_card))" in source


def test_multi_game_async_results_are_scoped_and_file_changes_require_game_stopped() -> None:
    source = APP_ENTRY.read_text(encoding="utf-8")

    assert "self.game_selection_generation = 0" in source
    assert "self.game_selection_generation += 1" in source
    assert "generation != self.game_selection_generation" in source
    assert "cartridge_id != self.cartridge.cartridge_id" in source
    assert "def _require_game_stopped" in source
    assert 'self._require_game_stopped("一键解锁工具")' in source
    assert 'self._require_game_stopped("移除本程序安装内容")' in source
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
    assert "plan_full_cleanup" in cleanup_method
    assert "self._post_ui(" in cleanup_method
    assert "不会删除游戏目录、已安装 DLC、原始备份、用户设置或运行日志" in cleanup_method


def test_client_confirms_before_forced_close_during_background_work() -> None:
    source = APP_ENTRY.read_text(encoding="utf-8")
    close_method = source.split("def _close", 1)[1].split(
        "def _show_download_state", 1
    )[0]

    assert "self._content_work_is_active()" in close_method
    assert "self.cache_cleanup_running" in close_method
    assert "任务仍在进行" in close_method
    assert "messagebox.askyesno" in close_method
    assert "self._cancel_downloads_for_close()" in close_method
    assert close_method.index("return") < close_method.index("self.window.destroy()")


def test_client_hides_outer_shell_and_destroys_children_before_root() -> None:
    source = APP_ENTRY.read_text(encoding="utf-8")
    descendant_method = source.split("def _destroy_widget_descendants", 1)[1].split(
        "def _close", 1
    )[0]
    close_method = source.split("def _close", 1)[1].split(
        "def _show_download_state", 1
    )[0]

    assert "widget.winfo_children()" in descendant_method
    assert descendant_method.index("self._destroy_widget_descendants(child)") < descendant_method.index(
        "child.destroy()"
    )
    assert "self._closing" in close_method
    assert close_method.index("self.window.withdraw()") < close_method.index(
        "self._hide_game_picker()"
    )
    assert close_method.index("self.window.withdraw()") < close_method.index(
        "self._close_announcement_dialog()"
    )
    assert close_method.index("self._close_announcement_dialog()") < close_method.index(
        "self._destroy_widget_descendants(self.window)"
    )
    assert close_method.index("self._destroy_widget_descendants(self.window)") < close_method.index(
        "self.window.quit()"
    )
    assert close_method.index("self.window.quit()") < close_method.index(
        "self.window.destroy()"
    )


def test_download_cancel_button_is_visible_during_patch_downloads() -> None:
    source = APP_ENTRY.read_text(encoding="utf-8")
    state_method = source.split("def _set_batch_download_state", 1)[1].split(
        "def _cancel_all_downloads", 1
    )[0]

    assert '"patch_downloading"' not in state_method.split(
        "interactive = state not in", 1
    )[1].split("}", 1)[0]
    assert "def _cancel_downloads_for_close" in source
    assert "self.download_queue.cancel_many(task_ids)" in source


def test_dangerous_bulk_uninstall_is_not_exposed() -> None:
    source = APP_ENTRY.read_text(encoding="utf-8")

    assert 'text="卸载全部 DLC"' not in source
    assert "def _uninstall_all_dlc" not in source
    assert 'text="移除本程序安装内容"' in source
    assert "游戏原有 DLC、其他来源的内容和下载缓存都不会被删除" in source


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
    assert 'messagebox.showinfo("一键解锁工具执行成功"' in source
    assert "self.unlock_workflow_active" in source
    finish_method = source.split("def _maybe_finish_unlock_workflow", 1)[1].split(
        "def _show_install_state", 1
    )[0]
    assert "self.patch_engine.audit_recorded" in finish_method
    assert "DLC 已安装，但补丁复检失败" in finish_method
    assert 'messagebox.showwarning(' in finish_method


def test_healthy_patch_fast_path_cleans_legacy_interference_files() -> None:
    source = APP_ENTRY.read_text(encoding="utf-8")
    start_method = source.split("def _start_unlock_workflow", 1)[1].split(
        "def _notify_patch_healthy_and_continue", 1
    )[0]
    assert "self.patch_engine.clean_interference_files" in start_method
    assert "补丁已经正确应用，但清理旧版残留干扰文件失败" in start_method
    finish_method = source.split("def _maybe_finish_unlock_workflow", 1)[1].split(
        "def _show_install_state", 1
    )[0]
    assert "已清理旧版残留干扰文件" not in finish_method
    assert "Cleaned %d interference file(s) for healthy patch" in start_method

    patch_applied_method = source.split("def _on_patch_applied", 1)[1].split(
        "def _on_patch_workflow_failed", 1
    )[0]
    assert "Cleaned %d interference file(s) while applying patch" in patch_applied_method


def test_patch_download_does_not_treat_gitlink_display_size_as_exact() -> None:
    source = APP_ENTRY.read_text(encoding="utf-8")
    method = source.split("def _download_spec_for_patch", 1)[1].split(
        "def _patch_asset_for", 1
    )[0]

    assert "expected_size=asset.size_bytes" in method
    assert "expected_sha256=(" in method
    assert "asset.sha256 if self._valid_sha256(asset.sha256) else None" in method


def test_patch_workflow_detects_security_software_quarantine() -> None:
    source = APP_ENTRY.read_text(encoding="utf-8")

    assert "def _missing_ready_patch_asset" in source
    assert "def _patch_security_software_message" in source
    assert "不要关闭整机防护" in source
    assert "不要添加整目录排除项" in source
    assert "self.download_queue.forget((spec.task_id,))" in source
    assert "Post-apply patch audit failed" in source
    assert "self.patch_engine.restore_original" in source


def test_patch_health_uses_recorded_content_hashes() -> None:
    source = APP_ENTRY.read_text(encoding="utf-8")
    method = source.split("def _patch_is_healthy", 1)[1].split(
        "def _valid_sha256", 1
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


def test_failed_download_source_switch_rolls_back_consistently() -> None:
    source = APP_ENTRY.read_text(encoding="utf-8")
    method = source.split("def _finish_download_source_error(", 1)[1].split(
        "def _on_download_source_ready", 1
    )[0]

    assert "self.settings_repository.save(previous)" in method
    assert "self.user_settings = previous" in method
    assert "self.context.updates.set_download_source(previous.download_source)" in method
    assert "self.cartridge_catalog.set_download_source(previous.download_source)" in method
    assert "self.announcement_service.set_download_source(previous.download_source)" in method
    assert "已自动恢复为" in method


def _download_source_ready_fixture():
    events: list[object] = []
    notifications: list[tuple[str, bool]] = []
    game_id = "stellaris"
    loaded = SimpleNamespace(
        cartridge=SimpleNamespace(
            adapter=SimpleNamespace(descriptor=SimpleNamespace(game_id=game_id))
        )
    )
    application = SimpleNamespace(
        download_source_generation=3,
        user_settings=SimpleNamespace(download_source="github"),
        cartridge=SimpleNamespace(
            adapter=SimpleNamespace(descriptor=SimpleNamespace(game_id=game_id)),
            platform_name="Steam",
            store_app_id="281990",
        ),
        selected_game_name="群星 (Stellaris)",
        platform_status=SimpleNamespace(
            configure=lambda **kwargs: events.append(("platform", kwargs))
        ),
        _activate_loaded_cartridge=lambda loaded, **kwargs: events.append("activate"),
        _sync_game_selector_values=lambda: events.append("sync_selector"),
        _set_game_selector_text=lambda value: events.append(("selector", value)),
        _scan_games=lambda: events.append("scan_games"),
        _refresh_catalog=lambda: events.append("refresh_catalog"),
        _notify=lambda message, error=False: notifications.append((message, error)),
    )
    return application, loaded, events, notifications


def test_download_source_success_notice_waits_for_cartridge_reload() -> None:
    switch_method = _app_method_source("_on_download_source_selected")
    ready_method = _app_method("_on_download_source_ready")
    ready_method.__globals__["provider_display_name"] = lambda source: {"github": "GitHub"}[source]
    application, loaded, events, notifications = _download_source_ready_fixture()

    assert "卡带已重新加载" not in switch_method

    assert ready_method(
        application,
        loaded,
        "github",
        3,
        remote_loaded=True,
    ) is True

    assert events.index("activate") < events.index("scan_games")
    assert events.index("scan_games") < events.index("refresh_catalog")
    assert notifications == [
        ("下载和程序更新源已切换为 GitHub，卡带已重新加载", False)
    ]


def test_download_source_cache_fallback_only_shows_warning() -> None:
    ready_method = _app_method("_on_download_source_ready")
    ready_method.__globals__["provider_display_name"] = lambda source: {"github": "GitHub"}[source]
    application, loaded, events, notifications = _download_source_ready_fixture()

    assert ready_method(
        application,
        loaded,
        "github",
        3,
        remote_loaded=False,
        fallback_message="连接超时",
    ) is True

    assert events[-1] == "refresh_catalog"
    assert notifications == [
        ("远程主表或当前卡带暂时不可用，已使用本地缓存；如仍异常请检查网络后重试。", True)
    ]
    assert all("卡带已重新加载" not in message for message, _ in notifications)


def test_patch_only_release_keeps_unlock_button_available() -> None:
    source = APP_ENTRY.read_text(encoding="utf-8")
    method = source.split("def _show_catalog(", 1)[1].split(
        "def _show_catalog_error", 1
    )[0]

    no_entries = method.split("if not entries:", 1)[1].split(
        "return", 1
    )[0]
    assert "if snapshot.patch_bundle is None:" in no_entries
    assert "self._set_batch_download_state(self.batch_download_state)" in no_entries
    assert "当前云端没有需要下载的 DLC；可直接安装补丁。" in no_entries


def test_repair_prepares_every_resource_before_destructive_cleanup() -> None:
    source = APP_ENTRY.read_text(encoding="utf-8")

    assert 'command=self._one_click_repair' in source
    assert "def _one_click_repair" in source
    assert 'self._set_batch_download_state("repairing")' in source
    assert "先准备并校验补丁与全部 DLC" in source
    assert "固化并校验当前安装的原生库保险库" in source
    assert "不批量预卸载" in source
    assert "def _poll_repair_preparation" in source
    assert "service.engine.ensure_disk_space(plan, replaced_existing=False)" in source
    assert "self.patch_engine.reset(game_root)" not in source
    assert "engine.repair_patch" in source
    repair_method = source.split("def _one_click_repair", 1)[1].split(
        "def _continue_repair_after_patch", 1
    )[0]
    assert "delete_cached_packages=True" not in repair_method
    assert "self.auto_install_attempted.discard" in repair_method
    assert "cartridge.remove_installed_dlc" not in repair_method
    assert "def _continue_repair_after_patch" in source
    assert "def _maybe_finish_repair_workflow" in source


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
    assert "游戏原有 DLC、其他来源的内容和下载缓存都不会被删除" in source
    # The old placeholder message must be gone entirely so users never see the
    # "按钮已预留" copy after an update.
    assert "按钮已预留" not in source
    assert "_show_patch_removal_placeholder" not in source
