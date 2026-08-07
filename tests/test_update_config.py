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


def test_update_settings_select_manifest_for_download_source(tmp_path: Path) -> None:
    paths = RuntimePaths(tmp_path)
    paths.ensure()
    _write(
        paths.update_defaults_config_file,
        {
            "manifest_url": "https://legacy.example/manifest.json",
            "manifest_urls": {
                "gitlink": "https://gitlink.example/update-manifest.json",
                "github": "https://github.example/update-manifest.json",
            },
        },
    )
    _write(
        paths.user_update_config_file,
        {
            "manifest_urls": {
                "github": "https://mirror.example/update-manifest.json"
            }
        },
    )

    settings = UpdateSettings.load(
        paths.update_config_file,
        defaults_path=paths.update_defaults_config_file,
        user_path=paths.user_update_config_file,
    )

    assert settings.active_manifest_url == (
        "https://gitlink.example/update-manifest.json"
    )
    github = settings.with_download_source("github")
    assert github.active_manifest_url == (
        "https://mirror.example/update-manifest.json"
    )
    assert settings.download_source == "gitlink"
