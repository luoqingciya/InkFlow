"""出站请求安全校验（规划书 §47）。

书源是**不可信输入**：一个恶意书源可以让 InkFlow 去请求云厂商的 metadata
端点（169.254.169.254）、本机管理接口（127.0.0.1）或局域网设备。

两道闸门：

1. **协议白名单** —— 只允许 http / https。
2. **地址黑名单** —— 拒绝回环、私有、链路本地、保留地址。

域名会被解析后校验，防止 ``evil.com`` 指向 ``127.0.0.1`` 绕过字面量检查。
解析结果带缓存，避免每个请求都走一次 DNS。
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from functools import lru_cache
from urllib.parse import urlparse

from inkflow_core.errors import ErrorCode, SourceError

__all__ = [
    "ALLOWED_SCHEMES",
    "UrlBlockedError",
    "check_url",
    "check_url_sync",
    "clear_dns_cache",
    "is_private_host_literal",
    "is_private_ip",
]

ALLOWED_SCHEMES = frozenset({"http", "https"})

_BLOCKED_HOSTNAMES = frozenset(
    {
        "localhost",
        "localhost.localdomain",
        "ip6-localhost",
        "ip6-loopback",
        # 云 metadata 常用别名
        "metadata",
        "metadata.google.internal",
    }
)

_BLOCKED_SUFFIXES = (".local", ".internal", ".localhost", ".home.arpa")


class UrlBlockedError(SourceError):
    """URL 被安全策略拒绝。"""

    code = ErrorCode.SOURCE_BLOCKED
    status_code = 403


def is_private_ip(value: str) -> bool:
    """判断字符串形式的 IP 是否属于不可外发范围。"""
    try:
        ip = ipaddress.ip_address(value)
    except ValueError:
        return False
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def is_private_host_literal(host: str) -> bool:
    """仅做**字面量**判断，不触发 DNS。"""
    lowered = host.lower().strip("[]")
    if lowered in _BLOCKED_HOSTNAMES:
        return True
    if lowered.endswith(_BLOCKED_SUFFIXES):
        return True
    return is_private_ip(lowered)


@lru_cache(maxsize=1024)
def _resolves_to_private(host: str) -> bool:
    """域名解析后是否落在内网。结果缓存，``clear_dns_cache()`` 可清空。"""
    try:
        infos = socket.getaddrinfo(host, None)
    except (socket.gaierror, UnicodeError, OSError):
        # 解析失败不在这里拦；后续真实请求会报连接错误，错误信息更准确
        return False
    # sockaddr 的第一个元素在不同平台上是 str 或 bytes，统一成 str 再判断
    return any(is_private_ip(str(info[4][0])) for info in infos)


def clear_dns_cache() -> None:
    """清空 DNS 判定缓存（测试用）。"""
    _resolves_to_private.cache_clear()


def check_url_sync(url: str, *, allow_private_network: bool = False) -> str:
    """同步校验 URL，返回规范化后的 URL。

    Raises:
        UrlBlockedError: 协议不允许，或目标地址属于内网且未显式放行。
    """
    parsed = urlparse(url)

    if parsed.scheme.lower() not in ALLOWED_SCHEMES:
        raise UrlBlockedError(
            f"书源请求被拒绝：不支持的协议 {parsed.scheme!r}",
            details={"url": url, "scheme": parsed.scheme},
        )

    host = parsed.hostname
    if not host:
        raise UrlBlockedError("书源请求被拒绝：URL 缺少主机名", details={"url": url})

    if allow_private_network:
        return url

    if is_private_host_literal(host):
        raise UrlBlockedError(
            f"书源请求被拒绝：{host} 属于内网 / 回环地址",
            details={"url": url, "host": host},
        )

    if _resolves_to_private(host):
        raise UrlBlockedError(
            f"书源请求被拒绝：{host} 解析到内网地址",
            details={"url": url, "host": host},
        )

    return url


async def check_url(url: str, *, allow_private_network: bool = False) -> str:
    """``check_url_sync`` 的异步包装，DNS 解析放到线程池避免阻塞事件循环。"""
    return await asyncio.to_thread(check_url_sync, url, allow_private_network=allow_private_network)
