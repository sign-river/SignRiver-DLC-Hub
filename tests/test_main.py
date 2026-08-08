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


def test_find_usable_module_skips_broken_and_excluded(tmp_path) -> None:
    import json

    from signriver_launcher.main import _find_usable_module

    versions = tmp_path / "versions"
    for version in ("0.1.0", "0.1.1", "0.1.2"):
        directory = versions / version
        directory.mkdir(parents=True)
        (directory / "module.json").write_text(
            json.dumps(
                {
                    "version": version,
                    "api_version": 1,
                    "entrypoint": "app_entry.py:create_application",
                }
            ),
            encoding="utf-8",
        )
        (directory / "app_entry.py").write_text("x", encoding="utf-8")

    (versions / "0.1.2" / "app_entry.py").unlink()

    assert _find_usable_module(versions, set()) == "0.1.1"
    assert _find_usable_module(versions, {"0.1.1"}) == "0.1.0"
    assert _find_usable_module(versions, {"0.1.0", "0.1.1"}) is None
