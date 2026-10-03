"""契约测试：把 ``check_*`` 跑在测试桩上。

真实引擎（Playwright 等）**复用同一批 check_ 函数**再加一组用例 ——
见 ``test_playwright.py``。
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest

from tests.browser import contract
from tests.browser.stub import StubBrowserProvider

pytestmark = pytest.mark.integration


@pytest.fixture
async def provider() -> AsyncGenerator[StubBrowserProvider]:
    item = StubBrowserProvider()
    try:
        yield item
    finally:
        await item.close()


async def test_start_and_close_are_idempotent(provider: StubBrowserProvider) -> None:
    await contract.check_start_and_close_are_idempotent(provider)


async def test_fetch_returns_html(provider: StubBrowserProvider, page_url: str) -> None:
    await contract.check_fetch_returns_html(provider, page_url)


async def test_unreachable_url_raises_browser_error(
    provider: StubBrowserProvider, closed_port_url: str
) -> None:
    await contract.check_unreachable_url_raises_browser_error(provider, closed_port_url)


async def test_timeout_is_enforced(provider: StubBrowserProvider, hanging_url: str) -> None:
    await contract.check_timeout_is_enforced(provider, hanging_url)


async def test_js_is_not_silently_ignored(provider: StubBrowserProvider, page_url: str) -> None:
    await contract.check_js_is_not_silently_ignored(provider, page_url)


async def test_cookies_are_json_serializable(provider: StubBrowserProvider) -> None:
    await contract.check_cookies_are_json_serializable(provider)


async def test_use_before_start_is_reported(provider: StubBrowserProvider, page_url: str) -> None:
    await contract.check_use_before_start_is_reported(provider, page_url)


async def test_use_after_close_is_reported(provider: StubBrowserProvider, page_url: str) -> None:
    await contract.check_use_after_close_is_reported(provider, page_url)


class _EmptyHtmlProvider(StubBrowserProvider):
    """故意违规：拿空串冒充成功。"""

    async def fetch_html(
        self, url: str, *, js: str | None = None, timeout: float | None = None
    ) -> str:
        return ""


async def test_contract_catches_empty_html(page_url: str) -> None:
    """契约本身要能抓到违规。

    否则它就是一堆恒真的断言 —— 而**假通过的用例比失败的用例更危险**。
    """
    provider = _EmptyHtmlProvider()
    try:
        with pytest.raises(AssertionError):
            await contract.check_fetch_returns_html(provider, page_url)
    finally:
        await provider.close()
