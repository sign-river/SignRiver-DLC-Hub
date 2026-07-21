"""Lightweight helpers for user-facing network errors in the publisher."""

from __future__ import annotations


def describe_network_error(
    error: BaseException,
    *,
    url: str = "",
    action: str = "",
) -> str:
    detail = str(error).strip() or error.__class__.__name__
    lower = detail.casefold()
    if isinstance(error, TimeoutError) or "timed out" in lower or "timeout" in lower:
        head = "连接超时"
    elif "name or service not known" in lower or "getaddrinfo failed" in lower:
        head = "无法解析域名"
    elif "connection refused" in lower:
        head = "连接被拒绝"
    elif "certificate" in lower or "ssl" in lower:
        head = "安全证书校验失败"
    elif "404" in detail or "not found" in lower:
        head = "资源不存在"
    elif "403" in detail or "forbidden" in lower:
        head = "没有访问权限"
    else:
        head = "网络请求失败"
    parts = [head]
    if action:
        parts.append(action)
    if url:
        display = url if len(url) <= 180 else f"{url[:177]}..."
        parts.append(f"链接：{display}")
    if detail and detail.casefold() not in head.casefold():
        parts.append(f"详情：{detail}")
    return "；".join(parts)


__all__ = ["describe_network_error"]
