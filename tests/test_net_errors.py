from __future__ import annotations

from signriver_app.infrastructure.net_errors import describe_network_error as app_describe
from signriver_common.net_errors import describe_network_error as common_describe
from signriver_launcher.net_errors import describe_network_error as launcher_describe
from signriver_publisher.models import PublisherCartridge
from signriver_publisher.net_errors import describe_network_error as publisher_describe


def test_timeout_includes_url_and_chinese_summary() -> None:
    message = app_describe(
        TimeoutError("timed out"),
        url="https://www.gitlink.org.cn/api/v1/repos/signriver/signriver-dlc-assets/releases",
        action="下载资源",
    )
    assert message.startswith("连接超时")
    assert "下载资源" in message
    assert "链接：https://www.gitlink.org.cn/" in message
    assert "详情：timed out" in message


def test_dns_failure_is_readable() -> None:
    message = app_describe(
        OSError("getaddrinfo failed"),
        url="https://example.invalid/file.zip",
    )
    assert message.startswith("无法解析域名")
    assert "链接：https://example.invalid/file.zip" in message


def test_long_url_is_truncated() -> None:
    url = "https://example.com/" + ("a" * 200)
    message = app_describe(TimeoutError("timed out"), url=url)
    assert "..." in message
    assert len(message) < len(url) + 80


def test_describe_is_idempotent() -> None:
    first = app_describe(TimeoutError("timed out"), url="https://example.com/a", action="下载")
    second = app_describe(OSError(first), url="https://example.com/b", action="重试")
    assert second == first


def test_host_and_app_helpers_stay_aligned() -> None:
    error = TimeoutError("The read operation timed out")
    kwargs = {"url": "https://example.com/x", "action": "探测"}
    assert app_describe(error, **kwargs) == common_describe(error, **kwargs)
    assert launcher_describe(error, **kwargs) == common_describe(error, **kwargs)
    assert publisher_describe(error, **kwargs) == common_describe(error, **kwargs)


def test_publisher_from_dict_restores_new_cartridge_defaults() -> None:
    for game_id, display, dlc_dir, exe in (
        ("cities_skylines", "都市天际线", "Files", "Cities.exe"),
        ("rimworld", "边缘世界", "Data", "RimWorldWin64.exe"),
    ):
        profile = PublisherCartridge.from_dict(
            {
                "game_id": game_id,
                "display_name": display,
                "release_tag": game_id,
            }
        )
        assert profile.dlc_relative_dir == dlc_dir
        assert profile.executable_relative_path == exe
        assert profile.dlc_import_naming_mode == "auto_prefix"
        assert profile.dlc_import_layout_mode == "children_if_root"
        assert profile.dlc_archive_root_mode == "strip_id_prefix"
        assert profile.install_directory_from_slug is True
