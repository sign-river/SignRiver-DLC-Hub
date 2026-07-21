"""Lightweight, allocation-only helpers for user-facing network errors.

These helpers must stay free of locks, logging side effects, and I/O so they
remain safe on download and UI threads.
"""

from __future__ import annotations


def describe_network_error(
    error: BaseException,
    *,
    url: str = "",
    action: str = "",
) -> str:
    """Turn a raw network exception into a short Chinese explanation.

    The original detail is kept so logs remain actionable; URL is attached when
    provided so timeouts and DNS failures are easy to diagnose.
    """
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
    elif "401" in detail or "unauthorized" in lower:
        head = "未授权访问"
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
