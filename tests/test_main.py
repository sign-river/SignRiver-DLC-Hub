from signriver_launcher.main import format_rollback_notice


def test_rollback_notice_mentions_versions_and_recovery_path() -> None:
    notice = format_rollback_notice("0.1.3", "0.1.2", "boom")

    assert "0.1.3" in notice
    assert "0.1.2" in notice
    assert "启动失败" in notice
    assert "已自动回滚" in notice
    assert "boom" in notice
    assert "检查更新" in notice
    assert "设置" in notice
    assert "日志" in notice