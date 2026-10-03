"""Playwright 引擎。

只装 headless 外壳（271MB），不装完整 chromium（433MB）—— 体积实测见 ADR-024。
"""

from __future__ import annotations

import contextlib
import os
from typing import TYPE_CHECKING, Any

from inkflow_browser_playwright.paths import browsers_dir
from inkflow_core.browser import (
    BrowserError,
    BrowserProvider,
    BrowserRegistry,
    BrowserUnavailableError,
)
from inkflow_core.paths import is_frozen

if TYPE_CHECKING:  # pragma: no cover
    from inkflow_core.config import BrowserConfig

__all__ = [
    "BROWSER_TARGET",
    "PlaywrightBrowserProvider",
    "install_hint",
    "register_playwright",
]

#: 只装 headless 外壳。完整 chromium 是 433MB，它只要 271MB。
BROWSER_TARGET = "chromium-headless-shell"

#: 浏览器没装时，Playwright 抛的错里带这句。
_MISSING_MARKER = "Executable doesn't exist"

#: 页面加载完成的判定。与 Legado 的 WebView 对齐（等 onPageFinished），
#: 而不是 networkidle —— 后者会把懒加载站点一直挂住。
_WAIT_UNTIL = "load"


def install_hint(config: BrowserConfig | None = None, *, target: str = BROWSER_TARGET) -> str:
    """浏览器未安装时的提示。

    解法写进 message —— 用户看到的就是这句话，只说「不可用」等于没帮上忙。
    """
    return (
        f"Playwright 浏览器未安装。执行下面的命令装上（约 270MB）：\n"
        f"  inkflow browser install\n"
        f"（或直接：python -m playwright install {target}）\n"
        f"浏览器会装到：{browsers_dir(config)}"
    )


def _load_playwright() -> Any:
    """导入 playwright。没装时给出安装方法。"""
    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:
        if is_frozen():
            raise BrowserUnavailableError(
                "这个构建（单文件可执行程序）没有带浏览器引擎，"
                "需要浏览器渲染的书源在这里不可用。\n"
                "用 pip / uv 安装的环境才支持：\n"
                '  pip install "inkflow-browser-playwright[playwright]"'
            ) from exc
        raise BrowserUnavailableError(
            '未安装 playwright。执行：\n  pip install "inkflow-browser-playwright[playwright]"'
        ) from exc
    return async_playwright


class PlaywrightBrowserProvider(BrowserProvider):
    """用 Playwright 驱动 Chromium 的浏览器引擎。"""

    name = "playwright"
    supports_js = True

    def __init__(self, config: BrowserConfig) -> None:
        self._config = config
        self._playwright: Any = None
        self._browser: Any = None
        self._context: Any = None

    async def start(self) -> None:
        if self._context is not None:
            return

        async_playwright = _load_playwright()

        # Playwright 从环境变量决定去哪找浏览器，必须在 start 之前设好。
        # 显式配了 install_dir 就以它为准；否则尊重用户自己设的环境变量，
        # 都没设才落到数据目录。
        target = str(browsers_dir(self._config))
        if self._config.install_dir:
            os.environ["PLAYWRIGHT_BROWSERS_PATH"] = target
        else:
            os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", target)

        try:
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(headless=self._config.headless)
            self._context = await self._browser.new_context()
        except Exception as exc:
            await self._cleanup()
            if _MISSING_MARKER in str(exc):
                raise BrowserUnavailableError(install_hint(self._config)) from exc
            raise BrowserUnavailableError(f"启动浏览器失败：{exc}") from exc

    async def close(self) -> None:
        await self._cleanup()

    async def fetch_html(
        self,
        url: str,
        *,
        js: str | None = None,
        timeout: float | None = None,
    ) -> str:
        context = self._require_context()
        seconds = self._config.timeout if timeout is None else timeout

        page = await context.new_page()
        try:
            await page.goto(url, wait_until=_WAIT_UNTIL, timeout=seconds * 1000)
            if js is not None:
                await page.evaluate(js)
            return await page.content()
        except Exception as exc:
            raise BrowserError(f"打开 {url} 失败：{exc}", kind="network") from exc
        finally:
            # 关页面失败不该盖掉上面真正的原因
            with contextlib.suppress(Exception):
                await page.close()

    async def cookies(self) -> list[dict[str, Any]]:
        context = self._require_context()
        return list(await context.cookies())

    def _require_context(self) -> Any:
        if self._context is None:
            raise BrowserUnavailableError("浏览器引擎未启动：先调用 start()")
        return self._context

    async def _cleanup(self) -> None:
        """逆序释放。**单个失败不影响其余** —— 关闭阶段的异常不该中断清理。"""
        context, self._context = self._context, None
        browser, self._browser = self._browser, None
        playwright, self._playwright = self._playwright, None

        if context is not None:
            with contextlib.suppress(Exception):
                await context.close()
        if browser is not None:
            with contextlib.suppress(Exception):
                await browser.close()
        if playwright is not None:
            with contextlib.suppress(Exception):
                await playwright.stop()


def register_playwright(registry: BrowserRegistry, *, replace: bool = False) -> None:
    """把 Playwright 引擎注册到注册表。

    与 ``register_legado()`` 同一套做法：由外层**显式调用**，不在 import 时注册。
    """
    registry.register("playwright", PlaywrightBrowserProvider, replace=replace)
