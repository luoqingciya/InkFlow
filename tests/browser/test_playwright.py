"""Playwright 引擎的契约测试。

**复用同一批 ``check_*`` 函数**（``tests/browser/contract.py``）——
两个引擎跑同一份契约，行为才不会慢慢分叉。

没装 playwright 时整组跳过：日常 CI 不装它（ADR-024 的 CI 分层）。
装法见 ``pyproject.toml`` 的 ``browser`` 依赖组。
"""

from __future__ import annotations

import importlib.util
import os
from collections.abc import AsyncGenerator

import pytest

from inkflow_browser_playwright import (
    BROWSER_TARGET,
    PlaywrightBrowserProvider,
    browsers_dir,
    install_hint,
    register_playwright,
)
from inkflow_core.browser import BrowserRegistry, BrowserUnavailableError
from inkflow_core.config import BrowserConfig
from tests.browser import contract

requires_playwright = pytest.mark.skipif(
    importlib.util.find_spec("playwright") is None,
    reason="没装 playwright —— 用 uv sync --group browser 装上",
)

pytestmark = [pytest.mark.browser, requires_playwright]


@pytest.fixture
async def provider(monkeypatch: pytest.MonkeyPatch) -> AsyncGenerator[PlaywrightBrowserProvider]:
    """真实引擎实例。

    浏览器位置固定成「环境变量里那个，否则数据目录」并交给 monkeypatch 还原 ——
    否则引擎写进环境变量的路径会漏给后面的用例。
    """
    monkeypatch.setenv(
        "PLAYWRIGHT_BROWSERS_PATH",
        os.environ.get("PLAYWRIGHT_BROWSERS_PATH") or str(browsers_dir()),
    )
    item = PlaywrightBrowserProvider(BrowserConfig(enabled=True, engine="playwright"))
    try:
        yield item
    finally:
        await item.close()


# ================================================================ 契约
#
# 与测试桩跑的是**同一批** check_ 函数。


async def test_start_and_close_are_idempotent(provider: PlaywrightBrowserProvider) -> None:
    await contract.check_start_and_close_are_idempotent(provider)


async def test_fetch_returns_html(provider: PlaywrightBrowserProvider, page_url: str) -> None:
    await contract.check_fetch_returns_html(provider, page_url)


async def test_unreachable_url_raises_browser_error(
    provider: PlaywrightBrowserProvider, closed_port_url: str
) -> None:
    await contract.check_unreachable_url_raises_browser_error(provider, closed_port_url)


async def test_timeout_is_enforced(provider: PlaywrightBrowserProvider, hanging_url: str) -> None:
    await contract.check_timeout_is_enforced(provider, hanging_url)


async def test_js_is_not_silently_ignored(
    provider: PlaywrightBrowserProvider, page_url: str
) -> None:
    await contract.check_js_is_not_silently_ignored(provider, page_url)


async def test_cookies_are_json_serializable(provider: PlaywrightBrowserProvider) -> None:
    await contract.check_cookies_are_json_serializable(provider)


async def test_use_before_start_is_reported(
    provider: PlaywrightBrowserProvider, page_url: str
) -> None:
    await contract.check_use_before_start_is_reported(provider, page_url)


async def test_use_after_close_is_reported(
    provider: PlaywrightBrowserProvider, page_url: str
) -> None:
    await contract.check_use_after_close_is_reported(provider, page_url)


# ================================================================ 引擎特有


async def test_missing_browser_reports_install_command(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """浏览器没装时要报出**安装命令**，而不是一句「不可用」。

    这条是 ADR-024 第 3 条：失败要看得见，且解法写进 message。
    """
    monkeypatch.delenv("PLAYWRIGHT_BROWSERS_PATH", raising=False)
    config = BrowserConfig(enabled=True, engine="playwright", install_dir=str(tmp_path / "empty"))
    provider = PlaywrightBrowserProvider(config)
    try:
        with pytest.raises(BrowserUnavailableError) as info:
            await provider.start()
    finally:
        await provider.close()

    assert "playwright install" in str(info.value)
    assert BROWSER_TARGET in str(info.value)


async def test_fetch_renders_page_script(
    provider: PlaywrightBrowserProvider, page_url: str
) -> None:
    """``js`` 要真的在页面里跑过 —— 这是「浏览器」与「HTTP 客户端」的分界。

    脚本改掉标题，取回来的 HTML 里就该是新标题。
    """
    await provider.start()

    html = await provider.fetch_html(page_url, js="document.title = '渲染过了'")

    assert "渲染过了" in html


# ================================================================ 路径与提示


def test_browsers_dir_defaults_to_data_dir(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    from inkflow_core.paths import reset_home_cache

    monkeypatch.setenv("INKFLOW_HOME", str(tmp_path))
    reset_home_cache()
    try:
        assert browsers_dir() == tmp_path / "browsers"
    finally:
        reset_home_cache()


def test_browsers_dir_honours_install_dir(tmp_path) -> None:
    config = BrowserConfig(install_dir=str(tmp_path / "shared"))

    assert browsers_dir(config) == tmp_path / "shared"


def test_install_hint_names_target_and_dir(tmp_path) -> None:
    hint = install_hint(BrowserConfig(install_dir=str(tmp_path / "b")))

    assert "playwright install" in hint
    assert BROWSER_TARGET in hint
    assert str(tmp_path / "b") in hint


def test_register_playwright_wires_registry() -> None:
    registry = BrowserRegistry()

    register_playwright(registry)

    assert registry.has("playwright")
    provider = registry.create(BrowserConfig(enabled=True, engine="playwright"))
    assert isinstance(provider, PlaywrightBrowserProvider)
