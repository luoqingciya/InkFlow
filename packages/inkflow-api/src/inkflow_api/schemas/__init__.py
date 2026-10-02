"""API 请求 / 响应模型。

领域模型（``inkflow_core.models``）直接用于响应体；这里只放 API 层特有的
包装类型与请求体 —— 不重复定义已经有领域模型的东西。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from inkflow_core.models import (
    Book,
    BookSource,
    Chapter,
    ChapterContent,
    DownloadTask,
    SearchResult,
)

__all__ = [
    "BookDetailResponse",
    "BookListResponse",
    "CacheStatsResponse",
    "ChapterContentResponse",
    "ChapterListResponse",
    "ErrorDetail",
    "ErrorResponse",
    "ExportRequestModel",
    "ExportResponse",
    "HealthResponse",
    "MessageResponse",
    "SearchResponse",
    "SettingsResponse",
    "SettingsUpdateRequest",
    "SourceImportRequest",
    "SourceImportResponse",
    "SourceListResponse",
    "SourceTestRequest",
    "SourceTestResponse",
    "SystemInfoResponse",
    "TaskCreateRequest",
    "TaskDetailResponse",
    "TaskItemsResponse",
    "TaskListResponse",
]


# ---------------------------------------------------------------- 通用


class ErrorDetail(BaseModel):
    """错误详情。"""

    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
    trace_id: str | None = None


class ErrorResponse(BaseModel):
    """统一错误响应体（规划书 §29）。"""

    error: ErrorDetail


class MessageResponse(BaseModel):
    """简单操作结果。"""

    ok: bool = True
    message: str = ""


# ---------------------------------------------------------------- 系统


class HealthResponse(BaseModel):
    """``GET /health`` —— 供 Desktop 启动时做就绪探测。"""

    status: Literal["ok", "degraded"] = "ok"
    version: str
    uptime_seconds: float = 0.0


class CacheStatsResponse(BaseModel):
    """HTTP 缓存概况。

    未启用缓存时字段形状保持一致，只是取零值 —— 客户端不需要分支处理。
    """

    enabled: bool
    entries: int
    size_bytes: int
    expired_entries: int
    max_size_bytes: int | None = None


class SystemInfoResponse(BaseModel):
    """``GET /api/v1/system/info`` —— 运行概况。"""

    version: str
    data_dir: str
    uptime_seconds: float
    source_count: int
    enabled_source_count: int
    book_count: int
    task_count: int
    active_task_count: int
    export_formats: list[str]
    source_formats: list[str]
    python_version: str
    platform: str
    cache: CacheStatsResponse


# ---------------------------------------------------------------- 搜索


class SearchResponse(BaseModel):
    """``GET /api/v1/search``。"""

    keyword: str
    items: list[SearchResult] = Field(default_factory=list)
    #: 各书源的失败信息，便于用户判断「为什么结果少了」
    source_errors: dict[str, str] = Field(default_factory=dict)
    total: int = 0


# ---------------------------------------------------------------- 书籍


class BookListResponse(BaseModel):
    """书库列表。"""

    items: list[Book] = Field(default_factory=list)
    total: int = 0
    limit: int = 50
    offset: int = 0


class BookDetailResponse(BaseModel):
    """书籍详情 + 来源信息。"""

    book: Book
    source: BookSource | None = None
    chapter_count: int = 0
    downloaded_count: int = 0


class ChapterListResponse(BaseModel):
    """目录。"""

    book_id: str
    chapters: list[Chapter] = Field(default_factory=list)
    total: int = 0


class ChapterContentResponse(BaseModel):
    """章节正文。"""

    chapter: Chapter
    content: ChapterContent


# ---------------------------------------------------------------- 书源


class SourceListResponse(BaseModel):
    """书源列表。"""

    items: list[BookSource] = Field(default_factory=list)
    total: int = 0


class SourceImportRequest(BaseModel):
    """导入书源。

    ``content`` 与 ``url`` 二选一。
    """

    format: str = "auto"
    content: str | None = None
    url: str | None = None
    enabled: bool = True


class SourceImportResponse(BaseModel):
    """导入结果。"""

    source: BookSource
    created: bool
    """``False`` 表示覆盖了同 ID 的既有书源。"""


class SourceTestRequest(BaseModel):
    """书源测试（规划书 §42）。"""

    kind: Literal["search", "info", "toc", "content"] = "search"
    keyword: str = "测试"
    url: str | None = None


class SourceTestResponse(BaseModel):
    """测试结果 + 调试信息（规划书 §43）。"""

    ok: bool
    kind: str
    source_id: str
    elapsed_ms: float
    count: int = 0
    #: 前若干条结果的摘要
    preview: list[dict[str, Any]] = Field(default_factory=list)
    error: str | None = None
    #: 规则编译后的结构，供 Source Debugger 展示
    debug: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------- 任务


class TaskCreateRequest(BaseModel):
    """创建下载任务。"""

    model_config = ConfigDict(extra="forbid")

    book_id: str
    start_chapter: int = Field(default=0, ge=0)
    end_chapter: int | None = Field(default=None, ge=0)
    concurrency: int | None = Field(default=None, ge=1, le=64)
    output_format: str | None = None
    output_path: str | None = None
    auto_start: bool = True


class TaskListResponse(BaseModel):
    """任务列表。"""

    items: list[DownloadTask] = Field(default_factory=list)
    total: int = 0


class TaskDetailResponse(BaseModel):
    """任务详情。"""

    task: DownloadTask
    book: Book | None = None


class TaskItemsResponse(BaseModel):
    """任务章节明细。"""

    task_id: str
    items: list[dict[str, Any]] = Field(default_factory=list)
    total: int = 0


# ---------------------------------------------------------------- 导出


class ExportRequestModel(BaseModel):
    """导出请求。"""

    model_config = ConfigDict(extra="forbid")

    format: str = "epub"
    output_path: str | None = None
    start_chapter: int = 0
    end_chapter: int | None = None


class ExportResponse(BaseModel):
    """导出结果。"""

    book_id: str
    format: str
    output_path: str
    chapter_count: int


# ---------------------------------------------------------------- 设置


class SettingsResponse(BaseModel):
    """当前生效的配置。"""

    server: dict[str, Any]
    download: dict[str, Any]
    export: dict[str, Any]
    cache: dict[str, Any]
    source: dict[str, Any]
    js: dict[str, Any]
    browser: dict[str, Any]
    log: dict[str, Any]


class SettingsUpdateRequest(BaseModel):
    """更新设置。

    只支持白名单内的键，避免通过 API 改掉 ``server.host`` 这类安全相关项。
    """

    model_config = ConfigDict(extra="forbid")

    default_export_format: str | None = None
    download_concurrency: int | None = Field(default=None, ge=1, le=64)
    download_timeout: float | None = Field(default=None, gt=0)
    cache_enabled: bool | None = None
    source_allow_private_network: bool | None = None
