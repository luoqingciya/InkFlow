"""桌面端浏览器桥的地址与协议约定。

**为什么需要一座桥**：后端（Python 进程）要渲染页面，而 Chromium 在
桌面端（Electron 进程）里。两个进程之间得有个约定 —— 桥就是那个约定。

方向是**后端 → 桌面端**，与平时的「桌面端调后端」相反，所以地址由
**桌面端启动后端时通过环境变量传进来**（不是写文件让后端去读）：

- 桌面端先起桥、拿到端口，再 spawn 后端 —— 没有竞态
- 后端不是桌面端起的（比如独立部署）时，这两个变量就是空的，
  ``engine = "electron"`` 会明确报错并指出改用 playwright

协议见 :mod:`inkflow_browser_electron.provider`。
"""

from __future__ import annotations

import os
from dataclasses import dataclass

__all__ = [
    "ENV_TOKEN",
    "ENV_URL",
    "HEADER_TOKEN",
    "BridgeEndpoint",
    "endpoint_from_env",
]

#: 桌面端写进后端环境变量的两个值。
ENV_URL = "INKFLOW_BROWSER_BRIDGE"
ENV_TOKEN = "INKFLOW_BROWSER_TOKEN"

#: 鉴权头。桥只监听回环，但仍然要 token ——
#: 否则本机任何进程都能借桌面端去抓任意地址。
HEADER_TOKEN = "X-Inkflow-Token"


@dataclass(frozen=True)
class BridgeEndpoint:
    """桥的地址与凭据。"""

    url: str
    token: str


def endpoint_from_env(environ: dict[str, str] | None = None) -> BridgeEndpoint | None:
    """从环境变量读桥的地址。没配返回 ``None``。"""
    source = os.environ if environ is None else environ
    url = (source.get(ENV_URL) or "").strip().rstrip("/")
    if not url:
        return None
    return BridgeEndpoint(url=url, token=(source.get(ENV_TOKEN) or "").strip())
