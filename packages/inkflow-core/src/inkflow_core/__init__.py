"""inkflow-core —— 核心领域模型、配置与存储抽象。

本包**不依赖**任何其他 InkFlow 包，也不做网络请求。
依赖方向：``core ← source ← legado``，``core ← api``，``api ← cli``。
"""

from typing import TYPE_CHECKING

from inkflow_core.config import Settings, get_settings, parse_size
from inkflow_core.errors import ErrorCode, InkFlowError, NotFoundError, SourceError, TaskError
from inkflow_core.log import JsonFormatter, setup_logging
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
from inkflow_core.paths import (
    ENV_HOME,
    InkFlowPaths,
    candidate_homes,
    get_paths,
    inkflow_home,
    reset_home_cache,
    runtime_dir,
)
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
__version__ = "0.1.0.dev1"

if TYPE_CHECKING:
    # 仅供类型检查器与 IDE 解析 ``__all__`` 里的 "Database"。
    # 运行时走下面的模块级 __getattr__ 惰性导入，这里不会真的执行。
    from inkflow_core.storage import Database

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
    # log
    "JsonFormatter",
    "setup_logging",
    # normalize
    "normalize_text",
    "normalize_book_name",
    "normalize_author",
    "content_hash",
    "hash_bytes",
    # paths
    "InkFlowPaths",
    "candidate_homes",
    "get_paths",
    "inkflow_home",
    "reset_home_cache",
    "runtime_dir",
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


def __getattr__(name: str) -> object:
    """惰性导出 ``Database``。

    ``inkflow_core.storage`` 会拉起 SQLAlchemy，而 CLI 只用得到路径约定与
    错误码 —— 无条件导入会让纯 HTTP 客户端白白带上整个数据库层。

    这是 PEP 562 的模块级 ``__getattr__``，对
    ``from inkflow_core import Database`` 的使用方完全透明。
    """
    if name == "Database":
        from inkflow_core.storage import Database

        return Database
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
