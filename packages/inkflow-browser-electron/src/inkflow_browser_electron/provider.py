"""桌面端 Electron 引擎。

**渲染在另一个进程里做**：后端只按协议跟桌面端的浏览器桥说话。好处是复用
Electron 自带的 Chromium —— 桌面端不必再多下 376MB。

代价是这个 provider **只在桌面端启动的后端里可用**；独立部署请用
``engine = "playwright"``。
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING, Any

import httpx

from inkflow_browser_electron.bridge import HEADER_TOKEN, BridgeEndpoint, endpoint_from_env
from inkflow_core.browser import (
    BrowserError,
    BrowserProvider,
    BrowserRegistry,
    BrowserUnavailableError,
)

if TYPE_CHECKING:  # pragma: no cover
    from inkflow_core.config import BrowserConfig

__all__ = ["ElectronBrowserProvider", "register_electron"]

#: 请求超时的余量。桥那边自己也会按 timeout 掐，这里多留一段网络往返 ——
#: 否则桥刚准备回「超时」，这边先把连接掐了，报出来的错就不是真原因。
_TIMEOUT_SLACK = 5.0


class ElectronBrowserProvider(BrowserProvider):
    """通过桌面端的浏览器桥渲染页面。"""

    name = "electron"
    supports_js = True

    def __init__(self, config: BrowserConfig, bridge: BridgeEndpoint | None = None) -> None:
        self._config = config
        self._bridge = bridge if bridge is not None else endpoint_from_env()
        self._client: httpx.AsyncClient | None = None

    async def start(self) -> None:
        if self._client is not None:
            return

        bridge = self._bridge
        if bridge is None:
            raise BrowserUnavailableError(
                "没有可用的桌面端浏览器桥。\n"
                'engine = "electron" 只在**桌面端启动的后端**里可用 —— '
                "渲染要用 Electron 进程里的 Chromium。\n"
                '独立运行后端时请把 [browser] 的 engine 改成 "playwright"。'
            )

        client = httpx.AsyncClient(
            base_url=bridge.url, timeout=self._config.timeout + _TIMEOUT_SLACK
        )
        try:
            response = await client.get("/health", headers=self._headers())
        except httpx.HTTPError as exc:
            await client.aclose()
            raise BrowserUnavailableError(f"连不上桌面端浏览器桥（{bridge.url}）：{exc}") from exc

        if response.status_code != 200:
            await client.aclose()
            raise BrowserUnavailableError(
                f"桌面端浏览器桥返回 HTTP {response.status_code}（{bridge.url}）"
            )
        self._client = client

    async def close(self) -> None:
        client, self._client = self._client, None
        if client is not None:
            with contextlib.suppress(Exception):
                await client.aclose()

    async def fetch_html(
        self, url: str, *, js: str | None = None, timeout: float | None = None
    ) -> str:
        client = self._require_client()
        seconds = self._config.timeout if timeout is None else timeout

        try:
            response = await client.post(
                "/render",
                json={"url": url, "js": js, "timeout": seconds},
                headers=self._headers(),
                timeout=seconds + _TIMEOUT_SLACK,
            )
        except httpx.HTTPError as exc:
            raise BrowserError(f"打开 {url} 失败：{exc}", kind="network") from exc

        payload = self._payload(response)
        if not payload.get("ok"):
            reason = payload.get("error") or f"HTTP {response.status_code}"
            raise BrowserError(f"打开 {url} 失败：{reason}", kind="render")

        html = payload.get("html")
        if not isinstance(html, str):
            raise BrowserError(f"打开 {url} 失败：桌面端没有返回 HTML", kind="render")
        return html

    async def cookies(self) -> list[dict[str, Any]]:
        client = self._require_client()
        try:
            response = await client.get("/cookies", headers=self._headers())
        except httpx.HTTPError as exc:
            raise BrowserError(f"读取 Cookie 失败：{exc}", kind="network") from exc

        payload = self._payload(response)
        cookies = payload.get("cookies")
        return list(cookies) if isinstance(cookies, list) else []

    # -- 内部 --------------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        bridge = self._bridge
        return {HEADER_TOKEN: bridge.token} if bridge is not None else {}

    def _require_client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise BrowserUnavailableError("浏览器引擎未启动：先调用 start()")
        return self._client

    def _payload(self, response: httpx.Response) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError as exc:
            raise BrowserError(
                f"桌面端浏览器桥返回的不是 JSON（HTTP {response.status_code}）",
                kind="protocol",
            ) from exc
        if not isinstance(payload, dict):
            raise BrowserError("桌面端浏览器桥返回的不是对象", kind="protocol")
        return payload


def register_electron(registry: BrowserRegistry, *, replace: bool = False) -> None:
    """把 Electron 引擎注册到注册表。

    与 ``register_playwright()`` 同一套做法：由外层**显式调用**，不在 import 时注册。
    """
    registry.register("electron", ElectronBrowserProvider, replace=replace)
