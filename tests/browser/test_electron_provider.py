"""桌面端 Electron 引擎的测试。

跑的是**真的 HTTP 桥**（测试替身），协议、鉴权、超时、错误形状都真验。

**没验的**：Electron 那边的隐藏窗口、Cookie 共享、JS 执行 ——
那些只有实机跑桌面端才算数。

契约部分复用 ``tests/browser/contract.py`` 的同一批 ``check_`` 函数。
"""

from __future__ import annotations

from collections.abc import AsyncGenerator, Iterator

import pytest

from inkflow_browser_electron import BridgeEndpoint, ElectronBrowserProvider, register_electron
from inkflow_core.browser import BrowserRegistry, BrowserUnavailableError
from inkflow_core.config import BrowserConfig
from tests.browser import contract
from tests.browser.bridge_stub import BridgeStub, start_bridge_stub

pytestmark = pytest.mark.integration

TOKEN = "test-token"


@pytest.fixture
def bridge() -> Iterator[BridgeStub]:
    stub = start_bridge_stub(TOKEN)
    try:
        yield stub
    finally:
        stub.stop()


@pytest.fixture
async def provider(bridge: BridgeStub) -> AsyncGenerator[ElectronBrowserProvider]:
    item = ElectronBrowserProvider(
        BrowserConfig(enabled=True, engine="electron"),
        bridge=BridgeEndpoint(url=bridge.url, token=bridge.token),
    )
    try:
        yield item
    finally:
        await item.close()


# ================================================================ 契约
#
# 与 Playwright 引擎、测试桩跑的是**同一批** check_ 函数。


async def test_start_and_close_are_idempotent(provider: ElectronBrowserProvider) -> None:
    await contract.check_start_and_close_are_idempotent(provider)


async def test_fetch_returns_html(provider: ElectronBrowserProvider, page_url: str) -> None:
    await contract.check_fetch_returns_html(provider, page_url)


async def test_unreachable_url_raises_browser_error(
    provider: ElectronBrowserProvider, closed_port_url: str
) -> None:
    await contract.check_unreachable_url_raises_browser_error(provider, closed_port_url)


async def test_timeout_is_enforced(provider: ElectronBrowserProvider, hanging_url: str) -> None:
    await contract.check_timeout_is_enforced(provider, hanging_url)


async def test_js_is_not_silently_ignored(provider: ElectronBrowserProvider, page_url: str) -> None:
    await contract.check_js_is_not_silently_ignored(provider, page_url)


async def test_cookies_are_json_serializable(provider: ElectronBrowserProvider) -> None:
    await contract.check_cookies_are_json_serializable(provider)


async def test_use_before_start_is_reported(
    provider: ElectronBrowserProvider, page_url: str
) -> None:
    await contract.check_use_before_start_is_reported(provider, page_url)


async def test_use_after_close_is_reported(
    provider: ElectronBrowserProvider, page_url: str
) -> None:
    await contract.check_use_after_close_is_reported(provider, page_url)


# ================================================================ 协议细节


async def test_js_is_passed_to_the_bridge(
    provider: ElectronBrowserProvider, bridge: BridgeStub, page_url: str
) -> None:
    """脚本要**原样**递到桥那边 —— 桥负责在页面里跑它。"""
    await provider.start()

    await provider.fetch_html(page_url, js="document.title")

    assert bridge.renders[-1]["js"] == "document.title"


async def test_timeout_is_passed_to_the_bridge(
    provider: ElectronBrowserProvider, bridge: BridgeStub, page_url: str
) -> None:
    """超时要交给桥自己掐 —— 后端单方面掐断，报出来的错就不是真原因。"""
    await provider.start()

    await provider.fetch_html(page_url, timeout=2.5)

    assert bridge.renders[-1]["timeout"] == 2.5


async def test_wrong_token_is_rejected(bridge: BridgeStub) -> None:
    """token 不对要明确报错 —— 桥只监听回环，但不能让本机任意进程借用它。"""
    provider = ElectronBrowserProvider(
        BrowserConfig(enabled=True, engine="electron"),
        bridge=BridgeEndpoint(url=bridge.url, token="wrong"),
    )
    try:
        with pytest.raises(BrowserUnavailableError):
            await provider.start()
    finally:
        await provider.close()


async def test_missing_bridge_names_the_way_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """没配桥时要**说清为什么**，并指出改用 playwright。

    独立运行后端时就是这个情况 —— engine 还写着 electron。
    """
    monkeypatch.delenv("INKFLOW_BROWSER_BRIDGE", raising=False)
    provider = ElectronBrowserProvider(BrowserConfig(enabled=True, engine="electron"))

    with pytest.raises(BrowserUnavailableError) as info:
        await provider.start()

    message = str(info.value)
    assert "桌面端" in message
    assert "playwright" in message


async def test_bridge_going_away_is_reported(bridge: BridgeStub) -> None:
    """桥停了要报得出来 —— 不能变成一个没人处理的连接错误。"""
    provider = ElectronBrowserProvider(
        BrowserConfig(enabled=True, engine="electron"),
        bridge=BridgeEndpoint(url=bridge.url, token=bridge.token),
    )
    bridge.stop()

    with pytest.raises(BrowserUnavailableError) as info:
        await provider.start()

    assert "连不上" in str(info.value)


def test_register_electron_wires_registry() -> None:
    registry = BrowserRegistry()

    register_electron(registry)

    assert registry.has("electron")
    provider = registry.create(BrowserConfig(enabled=True, engine="electron"))
    assert isinstance(provider, ElectronBrowserProvider)
