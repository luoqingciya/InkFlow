"""``BrowserProvider`` 的行为契约 —— 任何引擎实现都必须满足。

新引擎（Playwright / Electron ...）的测试**直接复用这里的 check_ 函数**，
不要各写一份：契约一旦散开，两个引擎的行为就会慢慢分叉，
而「换个引擎结果就不一样」正是这个接口要避免的事。
"""

from __future__ import annotations

import json

import pytest

from inkflow_core.browser import BrowserError, BrowserProvider, BrowserUnavailableError

__all__ = [
    "check_start_and_close_are_idempotent",
    "check_fetch_returns_html",
    "check_unreachable_url_raises_browser_error",
    "check_timeout_is_enforced",
    "check_js_is_not_silently_ignored",
    "check_cookies_are_json_serializable",
    "check_use_before_start_is_reported",
    "check_use_after_close_is_reported",
]


async def check_start_and_close_are_idempotent(provider: BrowserProvider) -> None:
    """start / close 可重复调用；close 在未启动时也安全。"""
    await provider.close()
    await provider.start()
    await provider.start()
    await provider.close()
    await provider.close()
    await provider.start()


async def check_fetch_returns_html(provider: BrowserProvider, url: str) -> None:
    """取得到页面时返回非空 HTML。"""
    await provider.start()

    html = await provider.fetch_html(url)

    assert isinstance(html, str)
    assert html.strip(), "fetch_html 返回了空内容 —— 不能拿空串冒充成功"


async def check_unreachable_url_raises_browser_error(provider: BrowserProvider, url: str) -> None:
    """连不上要报 ``BrowserError``，不能把底层异常原样漏出去。

    调用方按 kind 分支，漏出 httpx / 引擎自己的异常类型就等于没有契约。
    """
    await provider.start()

    with pytest.raises(BrowserError) as info:
        await provider.fetch_html(url)

    assert not isinstance(info.value, BrowserUnavailableError)
    assert info.value.kind != "unavailable"


async def check_timeout_is_enforced(provider: BrowserProvider, url: str) -> None:
    """``timeout`` 要真的生效 —— 引擎挂住不能把调用方一起挂住。"""
    await provider.start()

    with pytest.raises(BrowserError):
        await provider.fetch_html(url, timeout=0.2)


async def check_js_is_not_silently_ignored(provider: BrowserProvider, url: str) -> None:
    """不支持脚本的引擎必须报错，而不是假装跑过了。

    静默忽略会让书源以为 ``webJs`` 生效了，拿到的是没处理过的页面 ——
    这种「看起来对」的错误最难查。
    """
    await provider.start()

    if provider.supports_js:
        html = await provider.fetch_html(url, js="document.title")
        assert isinstance(html, str)
        return

    with pytest.raises(BrowserError) as info:
        await provider.fetch_html(url, js="1 + 1")

    assert info.value.kind == "unsupported"


async def check_cookies_are_json_serializable(provider: BrowserProvider) -> None:
    """Cookie 要能直接进 JSON（API 响应会把它序列化出去）。"""
    await provider.start()

    cookies = await provider.cookies()

    assert isinstance(cookies, list)
    json.dumps(cookies, ensure_ascii=False)


async def check_use_before_start_is_reported(provider: BrowserProvider, url: str) -> None:
    """没启动就用要报 ``BrowserUnavailableError``，不能抛底层异常。"""
    await provider.close()

    with pytest.raises(BrowserUnavailableError):
        await provider.fetch_html(url)


async def check_use_after_close_is_reported(provider: BrowserProvider, url: str) -> None:
    """关掉之后再用同样要报 ``BrowserUnavailableError``。"""
    await provider.start()
    await provider.close()

    with pytest.raises(BrowserUnavailableError):
        await provider.fetch_html(url)
