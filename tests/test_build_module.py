from __future__ import annotations

import json
from pathlib import Path

from tools.build_module import build, remove_unpublished_baseline_artifacts


def _write_module(root: Path, version: str) -> Path:
    module = root / version
    module.mkdir(parents=True)
    (module / "app_entry.py").write_text("def create_application(context): pass\n")
    (module / "module.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "name": "test",
                "version": version,
                "api_version": 1,
                "entrypoint": "app_entry.py:create_application",
            }
        ),
        encoding="utf-8",
    )
    return module


def test_all_versions_cleanup_removes_only_unpublished_baseline(tmp_path: Path) -> None:
    output = tmp_path / "dist"
    build(_write_module(tmp_path / "versions", "0.1.0"), output)
    current_archive, current_fragment = build(
        _write_module(tmp_path / "versions", "0.2.0"), output
    )

    remove_unpublished_baseline_artifacts(output)

    assert not (output / "SignRiver-DLC-Hub-module-v0.1.0.zip").exists()
    assert not (output / "SignRiver-DLC-Hub-module-v0.1.0.release.json").exists()
    assert current_archive.is_file()
    assert current_fragment.is_file()
