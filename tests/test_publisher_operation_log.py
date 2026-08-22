from __future__ import annotations

import signriver_publisher.operation_log as operation_log_module

from signriver_publisher.operation_log import OperationLog


def test_operation_log_survives_restart_and_stays_bounded(tmp_path) -> None:
    log = OperationLog(tmp_path)
    for index in range(505):
        log.append(f"[{index:03d}] 上传事件")

    restored = OperationLog(tmp_path).load()

    assert len(restored) == 500
    assert restored[0] == "[005] 上传事件"
    assert restored[-1] == "[504] 上传事件"


def test_operation_log_retries_a_transient_windows_replace_denial(tmp_path, monkeypatch) -> None:
    log = OperationLog(tmp_path)
    original_replace = operation_log_module.os.replace
    attempts = 0

    def flaky_replace(source, destination) -> None:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise PermissionError("temporarily locked")
        original_replace(source, destination)

    monkeypatch.setattr(operation_log_module.os, "replace", flaky_replace)

    log.append("上传完成")

    assert attempts == 3
    assert log.load() == ["上传完成"]
    assert not list(tmp_path.glob("*.tmp"))
