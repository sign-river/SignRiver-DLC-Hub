"""Tests for 0.1.5 UI polish: human-friendly byte units and mandatory updates.

Byte formatting is module-level in ``app_entry.py``; the UI class cannot be
imported without a Tk/launcher context, so the helpers are extracted from the
source via ``ast`` and executed in an isolated namespace (same approach as
``test_ui_theme.py``).
"""
from __future__ import annotations

import ast
from pathlib import Path

APP_ENTRY = Path(__file__).parents[1] / "app" / "versions" / "0.1.0" / "app_entry.py"
SOURCE = APP_ENTRY.read_text(encoding="utf-8")
MODULE = ast.parse(SOURCE)


def _extract_function(name: str, namespace: dict | None = None):
    node = next(
        node for node in MODULE.body
        if isinstance(node, ast.FunctionDef) and node.name == name
    )
    ns: dict = {} if namespace is None else namespace
    exec(compile(ast.Module(body=[node], type_ignores=[]), APP_ENTRY, "exec"), ns)  # noqa: S102
    return ns[name]


def test_format_size_uses_kb_mb_gb_units() -> None:
    format_size = _extract_function("_format_size")
    assert format_size(512) == "512.0 B"
    assert format_size(1024) == "1.0 KB"
    assert format_size(1536 * 1024) == "1.5 MB"
    assert format_size(2 * 1024 * 1024) == "2.0 MB"
    assert format_size(3.5 * 1024**3) == "3.5 GB"


def test_format_speed_appends_per_second() -> None:
    namespace: dict = {"_format_size": _extract_function("_format_size")}
    format_speed = _extract_function("_format_speed", namespace=namespace)
    assert format_speed(1048576) == "1.0 MB/s"
    assert format_speed(512 * 1024) == "512.0 KB/s"


def test_update_check_consumes_mandatory_flag() -> None:
    on_checked = next(
        node for node in MODULE.body
        if isinstance(node, ast.ClassDef) and node.name == "DlcHubApplication"
    )
    method = next(
        node for node in on_checked.body
        if isinstance(node, ast.FunctionDef) and node.name == "_on_checked"
    )
    body = ast.get_source_segment(SOURCE, method) or ""
    assert "if release.mandatory:" in body
    assert "messagebox.showinfo(" in body
    # The non-mandatory path must keep the askyesno skip flow.
    assert "messagebox.askyesno(" in body


def test_no_hardcoded_kib_or_mib_ui_labels() -> None:
    # UI-facing byte formatting should go through _format_size/_format_speed.
    for line in SOURCE.splitlines():
        if "MiB" in line or "KiB" in line:
            raise AssertionError(f"hardcoded MiB/KiB label remains: {line.strip()}")
