"""InkFlow API 客户端。

CLI 不实现任何业务逻辑 —— 它只是这个客户端的一层薄壳。
所有请求都打到 ``/api/v1``，与 Desktop 走完全相同的接口。
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from inkflow_cli.discovery import ServerLocation

__all__ = ["ApiError", "InkFlowClient"]


class ApiError(Exception):
    """服务端返回的结构化错误。"""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 0,
        details: dict[str, Any] | None = None,
        trace_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}
        self.trace_id = trace_id


class InkFlowClient:
    """异步 API 客户端。

    Args:
        location: 服务地址与 token。
        timeout: 请求超时（秒）。下载任务创建是异步的，不需要长超时，
            但搜索可能较慢，因此默认给足 60 秒。
    """

    def __init__(self, location: ServerLocation, *, timeout: float = 60.0) -> None:
        self.location = location
        self.timeout = timeout
        headers = {"Accept": "application/json"}
        if location.token:
            headers["Authorization"] = f"Bearer {location.token}"
        self._client = httpx.AsyncClient(
            base_url=location.base_url,
            headers=headers,
            timeout=httpx.Timeout(timeout),
        )

    async def __aenter__(self) -> InkFlowClient:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    # -- 底层 --------------------------------------------------------------

    async def request(self, method: str, path: str, **kwargs: Any) -> Any:
        """发起请求并解析响应。

        Raises:
            ApiError: 服务端返回错误结构，或连接失败。
        """
        try:
            response = await self._client.request(method, path, **kwargs)
        except httpx.ConnectError as exc:
            raise ApiError(
                "CONNECTION_REFUSED",
                f"无法连接 InkFlow 服务（{self.location.base_url}）。"
                "请先启动：uv run inkflow-server",
                details={"base_url": self.location.base_url, "origin": self.location.origin},
            ) from exc
        except httpx.TimeoutException as exc:
            raise ApiError(
                "CLIENT_TIMEOUT",
                f"请求超时（{self.timeout:g}s）：{method} {path}",
            ) from exc

        if response.status_code >= 400:
            raise self._to_error(response)

        if not response.content:
            return None
        content_type = response.headers.get("content-type", "")
        if "application/json" in content_type:
            return response.json()
        return response.text

    @staticmethod
    def _to_error(response: httpx.Response) -> ApiError:
        """把错误响应转成 ``ApiError``。"""
        try:
            payload = response.json()
            error = payload.get("error", {})
            return ApiError(
                code=str(error.get("code", "UNKNOWN")),
                message=str(error.get("message", response.text[:200])),
                status_code=response.status_code,
                details=error.get("details") or {},
                trace_id=error.get("trace_id"),
            )
        except (json.JSONDecodeError, AttributeError, ValueError):
            return ApiError(
                code="HTTP_ERROR",
                message=f"HTTP {response.status_code}: {response.text[:200]}",
                status_code=response.status_code,
            )

    # -- 系统 --------------------------------------------------------------

    async def health(self) -> dict[str, Any]:
        """健康检查（免鉴权）。"""
        return await self.request("GET", "/health")

    async def system_info(self) -> dict[str, Any]:
        """运行概况。"""
        return await self.request("GET", "/api/v1/system/info")

    # -- 搜索 --------------------------------------------------------------

    async def search(
        self,
        keyword: str,
        *,
        page: int = 1,
        limit: int = 50,
        sources: list[str] | None = None,
    ) -> dict[str, Any]:
        """聚合搜索。"""
        params: dict[str, Any] = {"q": keyword, "page": page, "limit": limit}
        if sources:
            params["sources"] = ",".join(sources)
        return await self.request("GET", "/api/v1/search", params=params)

    # -- 书籍 --------------------------------------------------------------

    async def list_books(self, *, limit: int = 50, offset: int = 0) -> dict[str, Any]:
        return await self.request("GET", "/api/v1/books", params={"limit": limit, "offset": offset})

    async def get_book(self, book_id: str) -> dict[str, Any]:
        return await self.request("GET", f"/api/v1/books/{book_id}")

    async def get_chapters(self, book_id: str, *, refresh: bool = False) -> dict[str, Any]:
        return await self.request(
            "GET", f"/api/v1/books/{book_id}/chapters", params={"refresh": refresh}
        )

    async def get_chapter_content(
        self, book_id: str, chapter_id: str, *, refresh: bool = False
    ) -> dict[str, Any]:
        return await self.request(
            "GET",
            f"/api/v1/books/{book_id}/chapters/{chapter_id}",
            params={"refresh": refresh},
        )

    async def export(
        self,
        book_id: str,
        *,
        fmt: str = "epub",
        output_path: str | None = None,
        start: int = 0,
        end: int | None = None,
    ) -> dict[str, Any]:
        """导出书籍。"""
        payload: dict[str, Any] = {"format": fmt, "start_chapter": start, "end_chapter": end}
        if output_path:
            payload["output_path"] = output_path
        return await self.request("POST", f"/api/v1/books/{book_id}/export", json=payload)

    # -- 书源 --------------------------------------------------------------

    async def list_sources(self) -> dict[str, Any]:
        return await self.request("GET", "/api/v1/sources")

    async def import_source(
        self,
        *,
        content: str | None = None,
        url: str | None = None,
        fmt: str = "auto",
        enabled: bool = True,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"format": fmt, "enabled": enabled}
        if content is not None:
            payload["content"] = content
        if url is not None:
            payload["url"] = url
        return await self.request("POST", "/api/v1/sources/import", json=payload)

    async def test_source(
        self,
        source_id: str,
        *,
        kind: str = "search",
        keyword: str = "测试",
        url: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"kind": kind, "keyword": keyword}
        if url:
            payload["url"] = url
        return await self.request("POST", f"/api/v1/sources/{source_id}/test", json=payload)

    async def inspect_rules(self, source_id: str) -> dict[str, Any]:
        return await self.request("GET", f"/api/v1/sources/{source_id}/rules")

    async def set_source_enabled(self, source_id: str, enabled: bool) -> dict[str, Any]:
        return await self.request(
            "PATCH", f"/api/v1/sources/{source_id}", json={"enabled": enabled}
        )

    async def delete_source(self, source_id: str) -> dict[str, Any]:
        return await self.request("DELETE", f"/api/v1/sources/{source_id}")

    # -- 任务 --------------------------------------------------------------

    async def create_task(
        self,
        book_id: str,
        *,
        start: int = 0,
        end: int | None = None,
        concurrency: int | None = None,
        fmt: str | None = None,
        output_path: str | None = None,
        auto_start: bool = True,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "book_id": book_id,
            "start_chapter": start,
            "end_chapter": end,
            "auto_start": auto_start,
        }
        if concurrency is not None:
            payload["concurrency"] = concurrency
        if fmt:
            payload["output_format"] = fmt
        if output_path:
            payload["output_path"] = output_path
        return await self.request("POST", "/api/v1/tasks", json=payload)

    async def list_tasks(self) -> dict[str, Any]:
        return await self.request("GET", "/api/v1/tasks")

    async def get_task(self, task_id: str) -> dict[str, Any]:
        return await self.request("GET", f"/api/v1/tasks/{task_id}")

    async def get_task_items(self, task_id: str) -> dict[str, Any]:
        return await self.request("GET", f"/api/v1/tasks/{task_id}/items")

    async def pause_task(self, task_id: str) -> dict[str, Any]:
        return await self.request("POST", f"/api/v1/tasks/{task_id}/pause")

    async def resume_task(self, task_id: str) -> dict[str, Any]:
        return await self.request("POST", f"/api/v1/tasks/{task_id}/resume")

    async def cancel_task(self, task_id: str) -> dict[str, Any]:
        return await self.request("POST", f"/api/v1/tasks/{task_id}/cancel")

    async def watch_task(self, task_id: str) -> AsyncIterator[dict[str, Any]]:
        """订阅任务进度事件（WebSocket）。

        Yields:
            进度事件字典，直到任务进入终态或连接断开。
        """
        import websockets

        uri = f"{self.location.ws_url}/ws/tasks/{task_id}"
        if self.location.token:
            uri = f"{uri}?token={self.location.token}"

        async with websockets.connect(uri) as socket:
            async for message in socket:
                yield json.loads(message)

    # -- 设置 --------------------------------------------------------------

    async def get_settings(self) -> dict[str, Any]:
        return await self.request("GET", "/api/v1/settings")
