"""浏览器运行时的核心契约（Milestone 4）。

这里**只有接口与注册机制**，没有任何引擎实现 —— 引擎由外层注册
（Playwright / Electron ...）。理由见 ADR-024。

之所以不把引擎写死在 core：**「谁提供浏览器」在不同部署形态下答案不同**。
桌面端已带 Electron（内含 Chromium），纯 CLI / 服务端没有。把某个引擎
焊进 core，等于替所有部署形态做了它们未必想要的选择。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover
    from inkflow_core.config import BrowserConfig

__all__ = [
    "BrowserError",
    "BrowserUnavailableError",
    "BrowserProvider",
    "BrowserFactory",
    "BrowserRegistry",
    "default_browser_registry",
]


class BrowserError(RuntimeError):
    """浏览器运行时错误。

    与 ``inkflow_core.errors`` 里的业务异常分开：这是**运行时能力**的错误，
    由调用方（书源适配器）翻译成业务异常 —— 与 JS 运行时同一套处理方式。
    """

    def __init__(self, message: str, *, kind: str = "runtime") -> None:
        super().__init__(message)
        self.kind = kind


class BrowserUnavailableError(BrowserError):
    """浏览器运行时不可用（未启用、引擎未注册、浏览器未安装）。"""

    def __init__(self, message: str) -> None:
        super().__init__(message, kind="unavailable")


class BrowserProvider(ABC):
    """浏览器引擎的契约。

    实现者只需保证这几件事，上层（书源适配器）不关心底下是哪个引擎。

    Attributes:
        name: 引擎名，与 ``BrowserConfig.engine`` 对应。
        supports_js: 能否在页面里执行**调用方给的**脚本（Legado 的 ``webJs``）。
            为 ``False`` 时 ``fetch_html(js=...)`` 必须报错而不是忽略 ——
            忽略会让书源以为脚本跑过了，拿到的是没处理过的页面。
    """

    name: str = "unknown"
    supports_js: bool = False

    @abstractmethod
    async def start(self) -> None:
        """启动引擎。可重复调用。

        Raises:
            BrowserUnavailableError: 浏览器本体不可用（未安装等）。
                错误信息里必须写清**怎么装** —— 用户看到的是 message。
        """

    @abstractmethod
    async def close(self) -> None:
        """关闭引擎并释放资源。未启动时静默返回，可重复调用。"""

    @abstractmethod
    async def fetch_html(
        self,
        url: str,
        *,
        js: str | None = None,
        timeout: float | None = None,
    ) -> str:
        """打开 URL，返回**渲染后**的 HTML。

        Args:
            url: 目标地址。
            js: 加载完成后在页面里执行的脚本（Legado 的 ``webJs``）。
            timeout: 覆盖配置里的超时。

        Raises:
            BrowserUnavailableError: 引擎未启动。
            BrowserError: 加载失败、超时，或引擎不支持 ``js``。
        """

    @abstractmethod
    async def cookies(self) -> list[dict[str, Any]]:
        """当前会话的 Cookie。

        返回可 JSON 序列化的列表（每项至少含 ``name`` / ``value``），
        无 Cookie 时返回空列表。
        """


#: 引擎工厂：``(浏览器配置) -> 引擎实例``
BrowserFactory = Callable[["BrowserConfig"], BrowserProvider]


class BrowserRegistry:
    """浏览器引擎注册表。

    与 ``SourceRegistry`` 同一套思路：core 不认识任何具体引擎，
    由外层在自己的包里注册工厂。
    """

    def __init__(self) -> None:
        self._factories: dict[str, BrowserFactory] = {}

    def register(self, name: str, factory: BrowserFactory, *, replace: bool = False) -> None:
        """注册引擎工厂。

        Raises:
            BrowserError: 同名引擎已注册且未指定 ``replace``。
        """
        if name in self._factories and not replace:
            raise BrowserError(f"浏览器引擎 {name!r} 已注册", kind="registry")
        self._factories[name] = factory

    def has(self, name: str) -> bool:
        """该引擎是否已注册。"""
        return name in self._factories

    def names(self) -> list[str]:
        """已注册的引擎名（排序，便于稳定输出）。"""
        return sorted(self._factories)

    def create(self, config: BrowserConfig) -> BrowserProvider:
        """按配置创建引擎实例。

        Raises:
            BrowserUnavailableError: 未启用，或配置的引擎没有注册。
        """
        if not config.enabled:
            raise BrowserUnavailableError(
                "浏览器运行时未启用。需要在 config.toml 的 [browser] 段设置 "
                "enabled = true 后重启服务。"
            )
        factory = self._factories.get(config.engine)
        if factory is None:
            available = "、".join(self.names()) or "（无）"
            raise BrowserUnavailableError(
                f"没有可用的浏览器引擎 {config.engine!r}。已注册：{available}。"
                f"请安装对应的引擎实现，或把 [browser] 段的 engine 改成已注册的引擎。"
            )
        return factory(config)


#: 进程级默认注册表。多实例场景（测试）请自行 new 一个。
default_browser_registry = BrowserRegistry()
