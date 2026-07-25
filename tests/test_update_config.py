from __future__ import annotations

import json
from pathlib import Path

from signriver_launcher.config import UpdateSettings
from signriver_launcher.paths import RuntimePaths


def _write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def test_update_settings_layer_user_over_legacy_over_defaults(tmp_path: Path) -> None:
    paths = RuntimePaths(tmp_path)
    paths.ensure()
    _write(paths.update_defaults_config_file, {"channel": "stable", "timeout_seconds": 10})
    _write(paths.update_config_file, {"channel": "beta", "check_on_startup": True})
    _write(paths.user_update_config_file, {"channel": "nightly", "timeout_seconds": 30})

    settings = UpdateSettings.load(
        paths.update_config_file,
        defaults_path=paths.update_defaults_config_file,
        user_path=paths.user_update_config_file,
    )

    assert settings.channel == "nightly"
    assert settings.timeout_seconds == 30
    assert settings.check_on_startup is True
