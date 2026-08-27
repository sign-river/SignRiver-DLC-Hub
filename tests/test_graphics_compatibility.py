from __future__ import annotations

import importlib.util
import sys
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
