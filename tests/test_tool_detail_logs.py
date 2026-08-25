from pathlib import Path


APP_ENTRY = Path(__file__).parents[1] / "app" / "versions" / "0.1.0" / "app_entry.py"


def test_tool_logs_are_keyed_and_notifications_do_not_write_into_them() -> None:
    source = APP_ENTRY.read_text(encoding="utf-8")
    assert "self.tool_center_logs: dict[str, list[str]]" in source
    assert "self.tool_center_active_log_key" in source
    notify = source[source.index("    def _notify("):source.index("    def _notify_patch_healthy_and_continue")]
    assert "_append_tool_log(message" not in notify


def test_tool_actions_capture_async_results_with_originating_key() -> None:
    source = APP_ENTRY.read_text(encoding="utf-8")
    assert "tool_key = f\"helper:{tool.tool_id}\"" in source
    assert "tool_key=key" in source
    assert "builtin:patch-tool" in source
    assert "builtin:support-collection" in source
    assert "builtin:security-products" in source
    assert "builtin:gpu-driver" in source


def test_tool_detail_reentry_does_not_clear_the_selected_log() -> None:
    source = APP_ENTRY.read_text(encoding="utf-8")
    detail = source[source.index("    def _show_tool_center_detail("):source.index("    def _tool_center_column_count")]
    assert "_set_active_tool_log" in detail
    assert "_clear_tool_logs()" not in detail
