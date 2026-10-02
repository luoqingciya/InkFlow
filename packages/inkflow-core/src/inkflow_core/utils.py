"""通用工具：时间与 ID 生成。"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime

__all__ = [
    "new_book_id",
    "new_chapter_id",
    "new_id",
    "new_source_id",
    "new_task_id",
    "new_task_item_id",
    "new_trace_id",
    "stable_id",
    "utcnow",
]


def utcnow() -> datetime:
    """返回带时区的当前 UTC 时间。"""
    return datetime.now(UTC)


def new_id(prefix: str, length: int = 16) -> str:
    """生成带类型前缀的随机 ID，例如 ``bk_9f3a1c2d4e5f6071``。

    前缀让 ID 在日志与 API 响应中自带类型信息，排障时不必回查数据库。
    """
    return f"{prefix}_{uuid.uuid4().hex[:length]}"


def stable_id(prefix: str, seed: str, length: int = 16) -> str:
    """由种子派生**确定性** ID。

    书源用它（种子是书源地址）：同一份输入永远得到同一个 ID，
    因此重复导入是幂等的 —— 不会在列表里堆出一串同源记录，
    也不会让已下载的章节与书籍失联。
    """
    digest = hashlib.sha256(seed.strip().rstrip("/").encode()).hexdigest()[:length]
    return f"{prefix}_{digest}"


def new_source_id() -> str:
    return new_id("src")


def new_book_id() -> str:
    return new_id("bk")


def new_chapter_id() -> str:
    return new_id("ch")


def new_task_id() -> str:
    return new_id("task")


def new_task_item_id() -> str:
    return new_id("ti")


def new_trace_id() -> str:
    """生成贯穿单次请求的 trace id。"""
    return uuid.uuid4().hex[:12]
