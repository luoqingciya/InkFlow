"""出站请求的 SSRF 校验（``inkflow_source.security``）。

**为什么单独一个文件**：这块之前只有间接覆盖 —— 集成测试里断言过
「`127.0.0.1` 被拒」和「`file://` 被拒」，也就是**只测了 IP 字面量**。
而书源是不可信输入，真正的绕过手段恰恰在另外两条路上：

- **域名**：`localhost`、`*.internal` 这类别名
- **DNS 重绑定**：域名先解析到公网、再解析到 `127.0.0.1`

那两条一行测试都没有。这里补上，并且把 DNS 解析换成**可控的桩** ——
真去解析外网域名会让测试依赖网络，而解析结果本身就不可控。
"""

from __future__ import annotations

import socket
from collections.abc import Iterator
from typing import Any

import pytest

from inkflow_source.security import (
    ALLOWED_SCHEMES,
    UrlBlockedError,
    check_url_sync,
    clear_dns_cache,
    is_private_host_literal,
    is_private_ip,
)

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _clean_dns_cache() -> Iterator[None]:
    """每个用例前后都清一次 —— DNS 判定是全局 lru_cache，会串味。"""
    clear_dns_cache()
    yield
    clear_dns_cache()


def _fake_resolver(mapping: dict[str, str | None]) -> Any:
    """造一个假的 ``getaddrinfo``：按域名返回固定 IP，``None`` 表示解析失败。"""

    def resolve(host: str, port: Any) -> list[Any]:
        target = mapping.get(host)
        if target is None:
            raise socket.gaierror(f"假解析器没有 {host} 的记录")
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (target, 0))]

    return resolve


# ================================================================ 协议白名单


def test_only_http_and_https_are_allowed() -> None:
    assert frozenset({"http", "https"}) == ALLOWED_SCHEMES


@pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://example.com/x", "gopher://x"])
def test_other_schemes_are_blocked(url: str) -> None:
    with pytest.raises(UrlBlockedError):
        check_url_sync(url)


def test_missing_hostname_is_blocked() -> None:
    with pytest.raises(UrlBlockedError):
        check_url_sync("http:///no-host")


# ================================================================ IP 判定


@pytest.mark.parametrize(
    "value",
    [
        "127.0.0.1",  # 回环
        "10.0.0.1",  # 私有
        "192.168.1.1",  # 私有
        "172.16.0.1",  # 私有
        "169.254.169.254",  # 云 metadata 的链路本地地址
        "0.0.0.0",  # 未指定
        "224.0.0.1",  # 组播
        "::1",  # IPv6 回环
        "fe80::1",  # IPv6 链路本地
    ],
)
def test_internal_addresses_are_private(value: str) -> None:
    assert is_private_ip(value) is True


@pytest.mark.parametrize("value", ["8.8.8.8", "1.1.1.1", "2001:4860:4860::8888"])
def test_public_addresses_are_not_private(value: str) -> None:
    assert is_private_ip(value) is False


def test_non_ip_text_is_not_treated_as_private() -> None:
    """不是 IP 的字符串交给域名那条路判，这里不能误判成「内网」。"""
    assert is_private_ip("example.com") is False
    assert is_private_ip("") is False


# ================================================================ 域名拦截
#
# 这一段是之前完全没覆盖的 —— 只测过 IP 字面量。


@pytest.mark.parametrize(
    "host",
    [
        "localhost",
        "LOCALHOST",  # 大小写不该绕过
        "localhost.localdomain",
        "ip6-localhost",
        "metadata",  # 云厂商 metadata 的别名
        "metadata.google.internal",
    ],
)
def test_blocked_hostnames(host: str) -> None:
    assert is_private_host_literal(host) is True


@pytest.mark.parametrize("host", ["box.local", "api.internal", "x.localhost", "y.home.arpa"])
def test_blocked_hostname_suffixes(host: str) -> None:
    """mDNS / 内网域名后缀 —— 这些解析出来多半是局域网地址。"""
    assert is_private_host_literal(host) is True


def test_bracketed_ipv6_is_unwrapped() -> None:
    """URL 里的 IPv6 带方括号（``http://[::1]/``），判定前要去掉。"""
    assert is_private_host_literal("[::1]") is True


def test_public_hostname_is_not_blocked_by_literal_check() -> None:
    assert is_private_host_literal("example.com") is False


def test_blocked_hostname_raises_with_details() -> None:
    with pytest.raises(UrlBlockedError) as info:
        check_url_sync("http://localhost/admin")

    assert info.value.code == "SOURCE_BLOCKED"
    assert info.value.details["host"] == "localhost"


# ================================================================ DNS 重绑定
#
# 这是字面量检查拦不住的那条路：域名看着人畜无害，解析出来是内网地址。


def test_hostname_resolving_to_loopback_is_blocked(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", _fake_resolver({"evil.com": "127.0.0.1"}))

    with pytest.raises(UrlBlockedError) as info:
        check_url_sync("http://evil.com/")

    assert "解析到内网" in str(info.value)


def test_hostname_resolving_to_metadata_address_is_blocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", _fake_resolver({"x.test": "169.254.169.254"}))

    with pytest.raises(UrlBlockedError):
        check_url_sync("http://x.test/")


def test_hostname_resolving_to_public_address_is_allowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", _fake_resolver({"good.test": "93.184.216.34"}))

    assert check_url_sync("http://good.test/") == "http://good.test/"


def test_dns_failure_does_not_block(monkeypatch: pytest.MonkeyPatch) -> None:
    """解析失败**不在这里拦** —— 后续真实请求会报连接错误，那个信息更准。

    在这里拦会把「域名打错了」报成「安全策略拒绝」，反而误导。
    """
    monkeypatch.setattr(socket, "getaddrinfo", _fake_resolver({}))

    assert check_url_sync("http://nx.test/") == "http://nx.test/"


def test_dns_result_is_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    """同一域名只解析一次 —— 否则每个请求都要走一次 DNS。"""
    calls: list[str] = []

    def counting_resolver(host: str, port: Any) -> list[Any]:
        calls.append(host)
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))]

    monkeypatch.setattr(socket, "getaddrinfo", counting_resolver)

    check_url_sync("http://good.test/")
    check_url_sync("http://good.test/")

    assert calls == ["good.test"]


def test_clear_dns_cache_forces_a_new_lookup(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def counting_resolver(host: str, port: Any) -> list[Any]:
        calls.append(host)
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))]

    monkeypatch.setattr(socket, "getaddrinfo", counting_resolver)

    check_url_sync("http://good.test/")
    clear_dns_cache()
    check_url_sync("http://good.test/")

    assert calls == ["good.test", "good.test"]


# ================================================================ 显式放行


def test_allow_private_network_skips_all_checks(monkeypatch: pytest.MonkeyPatch) -> None:
    """放行开关要能穿过**两道**闸门 —— 连 DNS 都不该解析。

    本地书源与测试都要用这个开关，绕过 DNS 是有意义的：
    放行了还去解析，等于白白多一次可能失败的调用。
    """
    calls: list[str] = []

    def counting_resolver(host: str, port: Any) -> list[Any]:
        calls.append(host)
        return []

    monkeypatch.setattr(socket, "getaddrinfo", counting_resolver)

    assert check_url_sync("http://127.0.0.1:8080/", allow_private_network=True)
    assert check_url_sync("http://localhost/", allow_private_network=True)

    assert calls == []


def test_scheme_is_checked_even_when_private_network_allowed() -> None:
    """放行的是**内网**，不是协议 —— `file://` 任何时候都该拒。"""
    with pytest.raises(UrlBlockedError):
        check_url_sync("file:///etc/passwd", allow_private_network=True)
