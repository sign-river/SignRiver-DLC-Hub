import json

import pytest

from tools.build_native_release import _validate_release_metadata


def _write_metadata(tmp_path, *, active_version="0.2.0", module_version="0.2.0"):
    app = tmp_path / "app"
    module_dir = app / "versions" / "0.2.0"
    module_dir.mkdir(parents=True)
    (app / "state.json").write_text(
        json.dumps({"active_version": active_version}), encoding="utf-8"
    )
    (module_dir / "module.json").write_text(
        json.dumps({"version": module_version}), encoding="utf-8"
    )


def test_validate_release_metadata_accepts_matching_versions(tmp_path) -> None:
    _write_metadata(tmp_path)

    _validate_release_metadata(tmp_path, "0.2.0")


def test_validate_release_metadata_rejects_active_version_mismatch(tmp_path) -> None:
    _write_metadata(tmp_path, active_version="0.1.0")

    with pytest.raises(SystemExit, match="active module and launcher versions must match"):
        _validate_release_metadata(tmp_path, "0.2.0")


def test_validate_release_metadata_rejects_missing_active_module(tmp_path) -> None:
    app = tmp_path / "app"
    app.mkdir()
    (app / "state.json").write_text(
        json.dumps({"active_version": "0.2.0"}), encoding="utf-8"
    )

    with pytest.raises(SystemExit, match="active module metadata does not exist"):
        _validate_release_metadata(tmp_path, "0.2.0")


def test_validate_release_metadata_rejects_module_version_mismatch(tmp_path) -> None:
    _write_metadata(tmp_path, module_version="0.1.0")

    with pytest.raises(
        SystemExit, match="active module metadata and launcher versions must match"
    ):
        _validate_release_metadata(tmp_path, "0.2.0")
