from __future__ import annotations

from signriver_app.infrastructure.net_errors import describe_network_error


def test_timeout_includes_url_and_chinese_summary() -> None:
    message = describe_network_error(
        TimeoutError("timed out"),
        url="https://www.gitlink.org.cn/api/v1/repos/signriver/signriver-dlc-assets/releases",
        action="下载资源",
    )
    assert message.startswith("连接超时")
    assert "下载资源" in message
    assert "链接：https://www.gitlink.org.cn/" in message
    assert "详情：timed out" in message


def test_dns_failure_is_readable() -> None:
    message = describe_network_error(
        OSError("getaddrinfo failed"),
        url="https://example.invalid/file.zip",
    )
    assert message.startswith("无法解析域名")
    assert "链接：https://example.invalid/file.zip" in message


def test_long_url_is_truncated() -> None:
    url = "https://example.com/" + ("a" * 200)
    message = describe_network_error(TimeoutError("timed out"), url=url)
    assert "..." in message
    assert len(message) < len(url) + 80
