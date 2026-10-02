"""本地 API 鉴权（规划书 §48）。

服务默认只监听 ``127.0.0.1``，但本机上的**任何**进程都能访问回环端口 ——
浏览器里的一个恶意页面就能对着 ``127.0.0.1:8765`` 发请求。
因此每次启动生成一次性 session token，Desktop 从后端进程的 stdout 读取它。

不设 token 的路由只有健康检查与文档 —— 它们不含用户数据。
"""

from __future__ import annotations

import hmac
import json
import secrets

from starlette.types import ASGIApp, Receive, Scope, Send

__all__ = [
    "EXEMPT_PATHS",
    "TOKEN_HEADER",
    "TokenAuthMiddleware",
    "generate_token",
]

TOKEN_HEADER = "authorization"

#: 免鉴权路径（精确匹配前缀）
EXEMPT_PATHS: tuple[str, ...] = (
    "/health",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/favicon.ico",
)


def generate_token(length: int = 32) -> str:
    """生成 URL 安全的随机 token。"""
    return secrets.token_urlsafe(length)


class TokenAuthMiddleware:
    """纯 ASGI 中间件，校验 ``Authorization: Bearer <token>``。

    用 ASGI 层而不是 FastAPI 依赖，是为了让鉴权对所有路由（含 WebSocket）
    统一生效，不会因为漏加依赖而开一个口子。
    """

    def __init__(self, app: ASGIApp, *, token: str, enabled: bool = True) -> None:
        self.app = app
        self.token = token
        self.enabled = enabled

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if not self.enabled or any(path.startswith(p) for p in EXEMPT_PATHS):
            await self.app(scope, receive, send)
            return

        provided = self._extract_token(scope)
        if provided is not None and hmac.compare_digest(provided, self.token):
            await self.app(scope, receive, send)
            return

        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 4401})
            return

        body = json.dumps(
            {
                "error": {
                    "code": "UNAUTHORIZED",
                    "message": "缺少或无效的 session token",
                    "details": {},
                    "trace_id": None,
                }
            },
            ensure_ascii=False,
        ).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": 401,
                "headers": [
                    (b"content-type", b"application/json; charset=utf-8"),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})

    @staticmethod
    def _extract_token(scope: Scope) -> str | None:
        """从 Authorization 头或 ``token`` 查询参数取值。

        查询参数是给 WebSocket 用的 —— 浏览器的 WebSocket API 不支持自定义头。
        """
        for raw_name, raw_value in scope.get("headers", []):
            if raw_name.decode("latin-1").lower() == TOKEN_HEADER:
                value = raw_value.decode("latin-1").strip()
                if value.lower().startswith("bearer "):
                    return value[7:].strip()
                return value or None

        query = scope.get("query_string", b"").decode("latin-1")
        for part in query.split("&"):
            if part.startswith("token="):
                return part[6:] or None
        return None
