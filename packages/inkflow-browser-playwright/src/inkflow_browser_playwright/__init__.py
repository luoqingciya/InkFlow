"""InkFlow 浏览器运行时：Playwright 引擎（Legado L3）。

按 ADR-024，引擎不写进 core，由外层**显式调用** :func:`register_playwright`
把它挂到注册表上。
"""

from inkflow_browser_playwright.paths import browsers_dir
from inkflow_browser_playwright.provider import (
    BROWSER_TARGET,
    PlaywrightBrowserProvider,
    install_hint,
    register_playwright,
)

__all__ = [
    "BROWSER_TARGET",
    "PlaywrightBrowserProvider",
    "browsers_dir",
    "install_hint",
    "register_playwright",
]
