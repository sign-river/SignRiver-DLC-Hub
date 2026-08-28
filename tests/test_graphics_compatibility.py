from __future__ import annotations

import importlib.util
import sys
import subprocess
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "app" / "versions" / "0.1.0" / "signriver_app" / "infrastructure" / "graphics_compatibility.py"
SPEC = importlib.util.spec_from_file_location("graphics_compatibility_under_test", MODULE_PATH)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


def test_parse_dxdiag_english_and_chinese_states() -> None:
    assert module.GraphicsCompatibilityService._parse_dxdiag(
        "DirectDraw Acceleration: Enabled\nDirect3D Acceleration: Disabled"
    ) == ("enabled", "disabled")
    assert module.GraphicsCompatibilityService._parse_dxdiag(
        "DirectDraw 加速: 已启用\nDirect3D 加速: 已禁用"
    ) == ("enabled", "disabled")


def test_non_windows_diagnosis_is_safe(monkeypatch) -> None:
    monkeypatch.setattr(module.os, "name", "posix")
    result = module.GraphicsCompatibilityService().diagnose()
    assert result.code == "graphics_not_applicable"
    assert not result.repairable


def test_dxdiag_retries_after_timeout_and_clears_partial_output(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(module.os, "name", "nt")
    calls = []

    def runner(_command, **_kwargs):
        calls.append(1)
        if len(calls) == 1:
            (tmp_path / "DxDiag.txt").write_text("partial", encoding="utf-8")
            raise subprocess.TimeoutExpired("dxdiag", 60)
        (tmp_path / "DxDiag.txt").write_text(
            "DirectDraw Acceleration: Enabled\nDirect3D Acceleration: Enabled",
            encoding="utf-8",
        )
        return type("Completed", (), {"returncode": 0, "stdout": ""})()

    # The service creates its own temp directory, so patch the temp-dir helper
    # to make the retry's stale-file cleanup observable.
    class TempDir:
        def __enter__(self):
            return str(tmp_path)
        def __exit__(self, *_args):
            return False

    original = module.tempfile.TemporaryDirectory
    module.tempfile.TemporaryDirectory = lambda **_kwargs: TempDir()
    try:
        service = module.GraphicsCompatibilityService(runner=runner)
        result = service.run_dxdiag(timeout=60, retry_delay=0)
    finally:
        module.tempfile.TemporaryDirectory = original
    assert result[:2] == ("enabled", "enabled")
    assert len(calls) == 2
