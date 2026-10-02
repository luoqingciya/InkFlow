"""统一错误处理（规划书 §29）。

响应体固定为::

    {
      "error": {
        "code": "SOURCE_TIMEOUT",
        "message": "书源请求超时",
        "details": {},
        "trace_id": "..."
      }
    }

客户端按 ``code`` 分支，不解析 ``message``。
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from inkflow_core.errors import ErrorCode, InkFlowError
from inkflow_core.utils import new_trace_id

__all__ = ["error_response", "install_error_handlers"]

#: HTTP 状态码 → 默认错误码
_STATUS_TO_CODE = {
    400: ErrorCode.VALIDATION_ERROR,
    401: ErrorCode.UNAUTHORIZED,
    403: ErrorCode.SOURCE_BLOCKED,
    404: ErrorCode.NOT_FOUND,
    409: ErrorCode.TASK_INVALID_STATE,
    422: ErrorCode.VALIDATION_ERROR,
    502: ErrorCode.SOURCE_EXECUTION_ERROR,
    504: ErrorCode.SOURCE_TIMEOUT,
}


def error_response(
    code: ErrorCode | str,
    message: str,
    *,
    status_code: int = 500,
    details: dict[str, Any] | None = None,
    trace_id: str | None = None,
) -> JSONResponse:
    """构造统一格式的错误响应。"""
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": str(code),
                "message": message,
                "details": details or {},
                "trace_id": trace_id,
            }
        },
    )


def install_error_handlers(app: FastAPI) -> None:
    """注册全部异常处理器。"""

    @app.exception_handler(InkFlowError)
    async def _inkflow_error(request: Request, exc: InkFlowError) -> JSONResponse:
        """业务异常：带稳定错误码。"""
        trace_id = getattr(request.state, "trace_id", None)
        return error_response(
            exc.code,
            exc.message,
            status_code=exc.status_code,
            details=exc.details,
            trace_id=trace_id,
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        """请求体校验失败：把字段错误放进 details，便于 CLI 定位。"""
        return error_response(
            ErrorCode.VALIDATION_ERROR,
            "请求参数校验失败",
            status_code=422,
            details={"errors": exc.errors()},
            trace_id=getattr(request.state, "trace_id", None),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        """Starlette 内置 HTTPException（如 404 路由不存在）。"""
        code = _STATUS_TO_CODE.get(exc.status_code, ErrorCode.INTERNAL_ERROR)
        return error_response(
            code,
            str(exc.detail),
            status_code=exc.status_code,
            trace_id=getattr(request.state, "trace_id", None),
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        """兜底：未预期异常也返回统一结构，不泄漏堆栈。

        完整堆栈写日志，响应里只给 trace_id —— 用户拿 trace_id 就能对上日志。
        """
        import logging

        trace_id = getattr(request.state, "trace_id", None) or new_trace_id()
        logging.getLogger("inkflow.api").exception(
            "未处理的异常 trace_id=%s path=%s", trace_id, request.url.path
        )
        return error_response(
            ErrorCode.INTERNAL_ERROR,
            "服务内部错误，请携带 trace_id 查看日志",
            status_code=500,
            trace_id=trace_id,
        )
