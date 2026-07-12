from __future__ import annotations

import json
import zipfile
from pathlib import Path

from signriver_app.domain import DownloadSnapshot, DownloadSpec, DownloadState, UserSettings
from signriver_app.infrastructure.diagnostics import DiagnosticExporter


def test_diagnostic_export_redacts_secrets_paths_and_url_queries(tmp_path: Path) -> None:
    app_root = tmp_path / "app"
    data_root = tmp_path / "data"
    log = data_root / "logs" / "launcher.log"
    log.parent.mkdir(parents=True)
    log.write_text(
        f"path={app_root} Authorization: secret-token\n"
        "url=https://example.test/file.zip?signature=secret\n"
        "Bearer abc.def.ghi\n",
        encoding="utf-8",
    )
    snapshot = DownloadSnapshot(
        DownloadSpec("task-1", "https://example.test/file.zip?token=secret", "file.zip"),
        DownloadState.FAILED,
        error="password=hunter2",
    )
    output = DiagnosticExporter(app_root, data_root).export(
        app_version="0.1.0", launcher_version="0.1.0",
        settings=UserSettings(), snapshots=(snapshot,), log_path=log,
    )
    with zipfile.ZipFile(output) as archive:
        report = json.loads(archive.read("diagnostic.json"))
        exported_log = archive.read("launcher.log").decode()
    assert set(report) == {"schema_version", "generated_at", "application", "settings", "tasks"}
    combined = json.dumps(report) + exported_log
    assert "hunter2" not in combined
    assert "secret-token" not in combined
    assert "signature=secret" not in combined
    assert "abc.def.ghi" not in combined
    assert str(app_root) not in combined
    assert "<APP_ROOT>" in exported_log
    assert snapshot.spec.url not in combined
