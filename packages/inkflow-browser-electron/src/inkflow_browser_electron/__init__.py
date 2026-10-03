"""InkFlow 浏览器运行时：桌面端 Electron 引擎。

复用 Electron 自带的 Chromium，桌面端不必再多下 376MB。
由外层**显式调用** :func:`register_electron` 挂到注册表上。
"""

from inkflow_browser_electron.bridge import (
    ENV_TOKEN,
    ENV_URL,
    HEADER_TOKEN,
    BridgeEndpoint,
    endpoint_from_env,
)
from inkflow_browser_electron.provider import ElectronBrowserProvider, register_electron

__all__ = [
    "ENV_TOKEN",
    "ENV_URL",
    "HEADER_TOKEN",
    "BridgeEndpoint",
    "ElectronBrowserProvider",
    "endpoint_from_env",
    "register_electron",
]
