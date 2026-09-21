from __future__ import annotations

import json
import zipfile
from pathlib import Path

from signriver_app.domain import (
    DownloadPurpose,
    DownloadSnapshot,
    DownloadSpec,
    DownloadStage,
    DownloadState,
    UserSettings,
)
from signriver_app.infrastructure.diagnostics import DiagnosticExporter
from signriver_common.problems import (
    ProblemAction,
    ProblemCategory,
    ProblemCode,
    ProblemReport,
    ProblemSeverity,
)


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
        DownloadSpec(
            "task-1",
            "https://example.test/file.zip?token=secret",
            "file.zip",
            "stellaris",
            expected_sha256="a" * 64,
            purpose=DownloadPurpose.PATCH_BINARY,
        ),
        DownloadState.FAILED,
        sha256="b" * 64,
        error="password=hunter2",
        failure_code=ProblemCode.PKG_HASH_MISMATCH.value,
        failure_stage=DownloadStage.VERIFY,
    )
    problem = ProblemReport.create(
        code=ProblemCode.PATCH_APPLY_FAILED,
        category=ProblemCategory.PATCH,
        severity=ProblemSeverity.ERROR,
        stage="apply",
        summary="补丁应用失败",
        suggestion="打开日志目录查看详情。",
        technical_details=(
            f"root={app_root} token=problem-secret "
            "https://example.test/report?id=private"
        ),
        task_id="task-1",
        filename="file.zip",
        expected_sha256="a" * 64,
        actual_sha256="b" * 64,
        allowed_actions=(ProblemAction.COPY_DETAILS,),
    )
    output = DiagnosticExporter(app_root, data_root).export(
        app_version="0.1.0", launcher_version="0.1.0",
        settings=UserSettings(),
        snapshots=(snapshot,),
        log_path=log,
        problems=(problem,),
    )
    with zipfile.ZipFile(output) as archive:
        report = json.loads(archive.read("diagnostic.json"))
        exported_log = archive.read("launcher.log").decode()
    assert set(report) == {
        "schema_version",
        "generated_at",
        "application",
        "settings",
        "tasks",
        "problems",
    }
    assert report["tasks"] == [
        {
            "task_id": "task-1",
            "filename": "file.zip",
            "purpose": DownloadPurpose.PATCH_BINARY.value,
            "state": DownloadState.FAILED.value,
            "bytes_downloaded": 0,
            "total_bytes": None,
            "attempt": 0,
            "failure_code": ProblemCode.PKG_HASH_MISMATCH.value,
            "failure_stage": DownloadStage.VERIFY.value,
            "expected_sha256": "a" * 64,
            "actual_sha256": "b" * 64,
            "error": "password=<REDACTED>",
        }
    ]
    assert report["problems"][0]["event_id"] == problem.event_id
    # 问题记录在创建时就会把用户主目录替换成 <user-home>。当出厂目录恰好位于
    # 主目录之下（macOS/SteamOS 的常见部署方式）时，导出阶段已经认不出完整的
    # 应用目录，只剩 <user-home> 前缀；两种形态都必须保证原始路径不出现。
    details = report["problems"][0]["technical_details"]
    assert " token=<REDACTED> https://example.test/report<redacted>" in details
    assert details.startswith(("root=<APP_ROOT>", "root=<user-home>"))
    assert str(app_root) not in details
    combined = json.dumps(report) + exported_log
    assert "hunter2" not in combined
    assert "secret-token" not in combined
    assert "problem-secret" not in combined
    assert "id=private" not in combined
    assert "signature=secret" not in combined
    assert "abc.def.ghi" not in combined
    assert str(app_root) not in combined
    assert "<APP_ROOT>" in exported_log
    assert snapshot.spec.url not in combined
