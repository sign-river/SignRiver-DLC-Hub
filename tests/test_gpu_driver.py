from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace


MODULE_PATH = Path(__file__).parents[1] / "app" / "versions" / "0.1.0" / "signriver_app" / "infrastructure" / "gpu_driver.py"
spec = importlib.util.spec_from_file_location("gpu_driver_under_test", MODULE_PATH)
assert spec and spec.loader
gpu_driver = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = gpu_driver
spec.loader.exec_module(gpu_driver)


def test_discover_gpu_drivers_keeps_integrated_and_discrete(monkeypatch) -> None:
    monkeypatch.setattr(gpu_driver.os, "name", "nt")
    payload = [
        {"Name": "OrayIddDriver Device", "AdapterCompatibility": "Oray", "DriverVersion": "1", "DriverDate": "/Date(1749600000000)/"},
        {"Name": "ToDesk Virtual Display Adapter", "AdapterCompatibility": "ToDesk", "DriverVersion": "2", "DriverDate": "/Date(1749600000000)/"},
        {"Name": "Intel(R) Graphics", "AdapterCompatibility": "Intel", "DriverVersion": "32", "DriverDate": "/Date(1769644800000)/"},
        {"Name": "NVIDIA GeForce RTX", "AdapterCompatibility": "NVIDIA", "DriverVersion": "3", "DriverDate": "/Date(1771113600000)/"},
    ]
    result = gpu_driver.discover_gpu_drivers(
        runner=lambda *_args, **_kwargs: SimpleNamespace(stdout=json.dumps(payload)),
        now_year=2026,
    )
    assert [item.name for item in result] == ["Intel(R) Graphics", "NVIDIA GeForce RTX"]
    assert result[0].driver_year == 2026

