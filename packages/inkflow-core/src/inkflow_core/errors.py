"""统一错误码与异常类型。

所有对外错误都携带稳定的 ``code``，客户端按 code 分支，不解析 message。
错误码一旦发布不再改变含义，只允许新增。
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

__all__ = ["ErrorCode", "InkFlowError", "NotFoundError", "SourceError", "TaskError"]


class ErrorCode(StrEnum):
    """对外暴露的错误码。"""

    # 通用
    INTERNAL_ERROR = "INTERNAL_ERROR"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    UNAUTHORIZED = "UNAUTHORIZED"
    NOT_FOUND = "NOT_FOUND"

    # 书籍
    BOOK_NOT_FOUND = "BOOK_NOT_FOUND"
    BOOK_NO_CHAPTERS = "BOOK_NO_CHAPTERS"

    # 书源
    SOURCE_NOT_FOUND = "SOURCE_NOT_FOUND"
    SOURCE_INVALID = "SOURCE_INVALID"
    SOURCE_DISABLED = "SOURCE_DISABLED"
    SOURCE_TIMEOUT = "SOURCE_TIMEOUT"
    SOURCE_EXECUTION_ERROR = "SOURCE_EXECUTION_ERROR"
    SOURCE_BLOCKED = "SOURCE_BLOCKED"

    # 搜索
    SEARCH_FAILED = "SEARCH_FAILED"
    SEARCH_NO_SOURCE = "SEARCH_NO_SOURCE"

    # 解析
    CHAPTER_PARSE_FAILED = "CHAPTER_PARSE_FAILED"
    CONTENT_PARSE_FAILED = "CONTENT_PARSE_FAILED"
    RULE_COMPILE_FAILED = "RULE_COMPILE_FAILED"

    # 下载
    DOWNLOAD_FAILED = "DOWNLOAD_FAILED"
    EXPORT_FAILED = "EXPORT_FAILED"

    # 任务
    TASK_NOT_FOUND = "TASK_NOT_FOUND"
    TASK_CANCELLED = "TASK_CANCELLED"
    TASK_INVALID_STATE = "TASK_INVALID_STATE"


class InkFlowError(Exception):
    """InkFlow 业务异常基类。

    Args:
        code: 稳定的错误码。
        message: 面向用户的中文描述。
        details: 结构化补充信息，会原样出现在 API 响应的 ``error.details``。
        status_code: 对应的 HTTP 状态码。
    """

    code: ErrorCode = ErrorCode.INTERNAL_ERROR
    status_code: int = 500

    def __init__(
        self,
        message: str,
        *,
        code: ErrorCode | None = None,
        details: dict[str, Any] | None = None,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code
        if status_code is not None:
            self.status_code = status_code
        self.details: dict[str, Any] = details or {}

    def to_dict(self, trace_id: str | None = None) -> dict[str, Any]:
        """转成 API 错误响应体。"""
        return {
            "error": {
                "code": str(self.code),
                "message": self.message,
                "details": self.details,
                "trace_id": trace_id,
            }
        }


class NotFoundError(InkFlowError):
    """资源不存在。"""

    code = ErrorCode.NOT_FOUND
    status_code = 404


class SourceError(InkFlowError):
    """书源相关错误。"""

    code = ErrorCode.SOURCE_EXECUTION_ERROR
    status_code = 502


class TaskError(InkFlowError):
    """下载任务相关错误。"""

    code = ErrorCode.TASK_INVALID_STATE
    status_code = 409
