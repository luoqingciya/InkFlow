"""inkflow-core —— 核心领域模型、配置与存储抽象。

本包**不依赖**任何其他 InkFlow 包，也不做网络请求。
依赖方向：``core ← source ← legado``，``core ← api``，``api ← cli``。
"""

from inkflow_core.config import Settings, get_settings, parse_size
from inkflow_core.errors import ErrorCode, InkFlowError, NotFoundError, SourceError, TaskError
from inkflow_core.models import (
    TASK_TRANSITIONS,
    Book,
    BookResult,
    BookSource,
    Chapter,
    ChapterContent,
    ChapterResult,
    CompatibilityLevel,
    ContentResult,
    DownloadTask,
    DownloadTaskItem,
    ExportFormat,
    RequestConfig,
    SearchResult,
    SourceFormat,
    SourceMeta,
    SourceRef,
    SourceType,
    TaskItemStatus,
    TaskStatus,
    can_transition,
)
from inkflow_core.normalize import (
    content_hash,
    hash_bytes,
    normalize_author,
    normalize_book_name,
    normalize_text,
)
from inkflow_core.paths import ENV_HOME, InkFlowPaths, get_paths, inkflow_home
from inkflow_core.storage import Database
from inkflow_core.utils import (
    new_book_id,
    new_chapter_id,
    new_id,
    new_source_id,
    new_task_id,
    new_task_item_id,
    new_trace_id,
    stable_id,
    utcnow,
)

#: 全项目唯一的版本号来源。其余包通过 [tool.hatch.version] 从这里读取。
__version__ = "0.1.0.dev0"

__all__ = [
    "__version__",
    # models
    "Book",
    "BookResult",
    "BookSource",
    "Chapter",
    "ChapterContent",
    "ChapterResult",
    "CompatibilityLevel",
    "ContentResult",
    "DownloadTask",
    "DownloadTaskItem",
    "ExportFormat",
    "RequestConfig",
    "SearchResult",
    "SourceFormat",
    "SourceMeta",
    "SourceRef",
    "SourceType",
    "TASK_TRANSITIONS",
    "TaskItemStatus",
    "TaskStatus",
    "can_transition",
    # config
    "Settings",
    "get_settings",
    "parse_size",
    # errors
    "ErrorCode",
    "InkFlowError",
    "NotFoundError",
    "SourceError",
    "TaskError",
    # normalize
    "normalize_text",
    "normalize_book_name",
    "normalize_author",
    "content_hash",
    "hash_bytes",
    # paths
    "InkFlowPaths",
    "get_paths",
    "inkflow_home",
    "ENV_HOME",
    # storage
    "Database",
    # utils
    "utcnow",
    "stable_id",
    "new_id",
    "new_source_id",
    "new_book_id",
    "new_chapter_id",
    "new_task_id",
    "new_task_item_id",
    "new_trace_id",
]
