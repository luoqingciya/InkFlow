"""测试用的浏览器引擎桩。

用**真实 HTTP** 取页面（不执行页面脚本），这样契约里「能取到 HTML /
取不到要报明确的错 / 超时要生效」都能真验，而不必下载浏览器。

它不是产品的一部分 —— 只用来把契约钉住，并给上层测试一个
不依赖真实浏览器的替身。
"""

from __future__ import annotations

from typing import Any

import httpx

from inkflow_core.browser import BrowserError, BrowserProvider, BrowserUnavailableError

__all__ = ["StubBrowserProvider"]

DEFAULT_TIMEOUT = 5.0


class StubBrowserProvider(BrowserProvider):
    """基于 HTTP 的假浏览器。"""

    name = "stub"
    supports_js = False

    def __init__(self, timeout: float = DEFAULT_TIMEOUT) -> None:
        self._timeout = timeout
        self._client: httpx.AsyncClient | None = None

    async def start(self) -> None:
        if self._client is None:
            self._client = httpx.AsyncClient(follow_redirects=True)

    async def close(self) -> None:
        client, self._client = self._client, None
        if client is not None:
            await client.aclose()

    async def fetch_html(
        self, url: str, *, js: str | None = None, timeout: float | None = None
    ) -> str:
        if js is not None:
            raise BrowserError(f"引擎 {self.name!r} 不能在页面里执行脚本", kind="unsupported")

        client = self._require_client()
        try:
            response = await client.get(url, timeout=timeout or self._timeout)
        except httpx.HTTPError as exc:
            raise BrowserError(f"打开 {url} 失败：{exc}", kind="network") from exc

        if response.status_code >= 400:
            raise BrowserError(f"打开 {url} 失败：HTTP {response.status_code}", kind="http")
        return response.text

    async def cookies(self) -> list[dict[str, Any]]:
        client = self._require_client()
        return [
            {
                "name": cookie.name,
                "value": cookie.value,
                "domain": cookie.domain or "",
                "path": cookie.path or "/",
            }
            for cookie in client.cookies.jar
        ]

    def _require_client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise BrowserUnavailableError("浏览器引擎未启动：先调用 start()")
        return self._client
