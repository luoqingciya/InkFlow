"""InkFlow 领域模型。

这些模型是**跨包共享的契约**：API 层直接序列化它们，Source 层返回它们，
Export 层消费它们。任何包都不得在此之外重新定义同义模型。
"""

from inkflow_core.models.book import Book
from inkflow_core.models.chapter import Chapter, ChapterContent
from inkflow_core.models.enums import (
    CompatibilityLevel,
    ExportFormat,
    SourceFormat,
    SourceType,
    TaskItemStatus,
    TaskStatus,
)
from inkflow_core.models.result import (
    BookResult,
    ChapterResult,
    ContentResult,
    SearchResult,
    SourceRef,
)
from inkflow_core.models.source import BookSource, RequestConfig, SourceMeta
from inkflow_core.models.task import (
    TASK_TRANSITIONS,
    DownloadTask,
    DownloadTaskItem,
    can_transition,
)

__all__ = [
    # enums
    "SourceType",
    "SourceFormat",
    "CompatibilityLevel",
    "TaskStatus",
    "TaskItemStatus",
    "ExportFormat",
    # source
    "BookSource",
    "RequestConfig",
    "SourceMeta",
    # book
    "Book",
    # chapter
    "Chapter",
    "ChapterContent",
    # task
    "DownloadTask",
    "DownloadTaskItem",
    "TASK_TRANSITIONS",
    "can_transition",
    # result
    "BookResult",
    "ChapterResult",
    "ContentResult",
    "SearchResult",
    "SourceRef",
]
