"""``BrowserRegistry`` 的行为。

注册表是「引擎由外层注册」这条决定的落点：core 不认识任何具体引擎，
而错误信息必须说清**怎么办**，不能只说「没有引擎」。
"""

from __future__ import annotations

import pytest

from inkflow_core.browser import (
    BrowserError,
    BrowserRegistry,
    BrowserUnavailableError,
    default_browser_registry,
)
from inkflow_core.config import BrowserConfig
from tests.browser.stub import StubBrowserProvider

pytestmark = pytest.mark.unit


def _factory(config: BrowserConfig) -> StubBrowserProvider:
    return StubBrowserProvider()


def test_disabled_config_is_rejected() -> None:
    """未启用时明确报错，并把启用方法写进 message。"""
    registry = BrowserRegistry()

    with pytest.raises(BrowserUnavailableError) as info:
        registry.create(BrowserConfig(enabled=False))

    assert "enabled" in str(info.value)
    assert "[browser]" in str(info.value)


def test_missing_engine_lists_available() -> None:
    """引擎没注册时要报出「已注册的有哪些」以及怎么改。"""
    registry = BrowserRegistry()
    registry.register("stub", _factory)

    with pytest.raises(BrowserUnavailableError) as info:
        registry.create(BrowserConfig(enabled=True, engine="playwright"))

    message = str(info.value)
    assert "playwright" in message
    assert "stub" in message
    assert "engine" in message


def test_registered_engine_is_created() -> None:
    registry = BrowserRegistry()
    registry.register("stub", _factory)

    provider = registry.create(BrowserConfig(enabled=True, engine="stub"))

    assert isinstance(provider, StubBrowserProvider)
    assert registry.has("stub")
    assert registry.names() == ["stub"]


def test_duplicate_registration_is_rejected() -> None:
    """重名注册要报错 —— 静默覆盖会让「谁把引擎换掉了」查不出来。"""
    registry = BrowserRegistry()
    registry.register("stub", _factory)

    with pytest.raises(BrowserError):
        registry.register("stub", _factory)

    registry.register("stub", _factory, replace=True)  # 显式替换可以


def test_default_registry_has_no_builtin_engine() -> None:
    """core 不自带任何引擎。

    引擎一律由外层**显式调用**注册（与 ``register_legado()`` 同一套做法），
    不在 import 时注册 —— 否则「装了哪个包」会悄悄改变运行时行为。
    """
    assert default_browser_registry.names() == []
