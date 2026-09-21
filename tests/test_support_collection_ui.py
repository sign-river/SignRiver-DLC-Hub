from __future__ import annotations

from pathlib import Path


APP_ENTRIES = tuple(
    Path(__file__).parents[1] / "app" / "versions" / version / "app_entry.py"
    for version in ("0.1.0", "0.2.0")
)


def test_tool_center_always_includes_the_builtin_support_collection_card() -> None:
    for app_entry in APP_ENTRIES:
        source = app_entry.read_text(encoding="utf-8")
        refresh_tool_center = source.split("def _refresh_tool_center", 1)[1].split(
            "def _show_guide_tool_detail", 1
        )[0]

        assert '"日志资料收集"' in refresh_tool_center
        assert "self._show_support_collection_tool," in refresh_tool_center
        assert refresh_tool_center.index('"日志资料收集"') > refresh_tool_center.index(
            "if self.host_platform == \"windows\":"
        )


def test_support_collection_detail_has_safe_background_actions_and_open_state() -> None:
    for app_entry in APP_ENTRIES:
        source = app_entry.read_text(encoding="utf-8")
        detail = source.split("def _show_support_collection_tool", 1)[1].split(
            "def _show_patch_tool", 1
        )[0]

        assert 'text="一键收集资料"' in detail
        assert 'text="打开日志收集文件夹"' in detail
        assert '点击下方按钮打开日志收集文件夹' in detail
        assert 'state="disabled" if self.support_collection_running else "normal"' in detail
        assert 'name="support-collection"' in detail
        assert "self.last_support_collection_output = result.output_dir" in detail
        assert "尚未找到本次会话生成的资料收集文件夹" in detail
        assert "self._open_path(output)" in detail


def test_support_collection_detail_keeps_the_collection_grid_compact() -> None:
    for app_entry in APP_ENTRIES:
        source = app_entry.read_text(encoding="utf-8")
        detail = source.split("def _show_support_collection_tool", 1)[1].split(
            "def _show_patch_tool", 1
        )[0]

        assert "本地采集 · 安全可控" not in detail
        assert '("问题记录", "本次会话与历史问题记录")' not in detail
        assert '("程序日志", "唏嘘南溪一键解锁工具日志")' in detail
        assert 'system_detail = {' in detail
        assert '"windows": "Windows DxDiag.txt"' in detail
        assert '"steamos": "SteamOS uname 与发行版信息"' in detail
        assert '"macos": "macOS system_profiler 图形与系统信息"' in detail
        assert "仅 Windows" not in detail


def test_support_collection_wording_avoids_user_facing_skip_language() -> None:
    for app_entry in APP_ENTRIES:
        source = app_entry.read_text(encoding="utf-8")

        assert "未找到的文件会安全跳过" not in source
        assert "发现并跳过" not in source
        assert "跳过 {skipped} 个已下载" not in source
        assert "个崩溃转储（.dmp）体积较大，未一并打包" in source
        assert "已有 {skipped} 项无需重新下载" in source
        assert "未运行（该工具不是可捕获输出的诊断工具）" in source
