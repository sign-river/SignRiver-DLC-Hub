from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace


MODULE_PATH = Path(__file__).parents[1] / "app" / "versions" / "0.1.0" / "signriver_app" / "infrastructure" / "security_software.py"
spec = importlib.util.spec_from_file_location("security_software_under_test", MODULE_PATH)
assert spec and spec.loader
security = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = security
spec.loader.exec_module(security)


def test_discover_security_products_parses_unique_absolute_executables() -> None:
    def runner(*_args, **_kwargs):
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps([
                {"displayName": "Windows Defender", "pathToSignedProductExe": r"C:\Program Files\Windows Defender\MSASCui.exe"},
                {"displayName": "Windows Defender", "pathToSignedProductExe": r"C:\ignored.exe"},
                {"displayName": "Huorong", "pathToSignedProductExe": "relative.exe"},
            ]),
        )


    products = security.discover_security_products(runner=runner)

    assert [product.name for product in products] == ["Windows Defender", "Huorong"]
    assert products[0].executable == Path(r"C:\Program Files\Windows Defender\MSASCui.exe")
    assert products[1].executable is None


def test_discover_security_products_returns_empty_on_bad_output() -> None:
    def runner(*_args, **_kwargs):
        return SimpleNamespace(returncode=0, stdout="not-json")

    assert security.discover_security_products(runner=runner) == ()


def test_windows_security_product_detection_only_allows_fixed_system_names() -> None:
    assert security.is_windows_security_product("Windows Defender")
    assert security.is_windows_security_product("Microsoft Defender Antivirus")
    assert security.is_windows_security_product("Windows Security")
    assert not security.is_windows_security_product("Huorong")
    assert not security.is_windows_security_product("Defender Helper")
