"""SQLite 表定义（规划书 §25）。

持久化模型与领域模型刻意分开：领域模型演进（改字段名、拆模型）不应
直接变成数据库迁移，两者之间留一层映射。

嵌套结构（request / meta / raw）以 JSON 文本存储 —— SQLite 的 JSON1
扩展可用，且这些字段只整体读写，不需要按内部键查询。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

__all__ = [
    "Base",
    "BookRow",
    "BookSourceRow",
    "ChapterContentRow",
    "ChapterRow",
    "DownloadTaskItemRow",
    "DownloadTaskRow",
    "HttpCacheRow",
    "SettingRow",
]


class Base(DeclarativeBase):
    """所有 ORM 表的基类。"""


class BookSourceRow(Base):
    """书源表。"""

    __tablename__ = "book_sources"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    url: Mapped[str] = mapped_column(String(1024))

    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    priority: Mapped[int] = mapped_column(Integer, default=0)

    source_type: Mapped[str] = mapped_column(String(32))
    source_format: Mapped[str] = mapped_column(String(32))
    compatibility_level: Mapped[str] = mapped_column(String(16), default="L0")
    rule_version: Mapped[str] = mapped_column(String(32), default="1.0")

    enabled_search: Mapped[bool] = mapped_column(Boolean, default=True)
    enabled_explore: Mapped[bool] = mapped_column(Boolean, default=False)

    # JSON 文本
    request_config: Mapped[str] = mapped_column(Text, default="{}")
    meta: Mapped[str] = mapped_column(Text, default="{}")
    raw: Mapped[str] = mapped_column(Text, default="{}")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class BookRow(Base):
    """书籍表。

    ``(source_id, source_book_url)`` 唯一：同一本书在同一书源下只有一条记录。
    """

    __tablename__ = "books"
    __table_args__ = (
        UniqueConstraint("source_id", "source_book_url", name="uq_books_source_url"),
        Index("ix_books_normalized_name", "normalized_name"),
        Index("ix_books_author", "author"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)

    name: Mapped[str] = mapped_column(String(512), index=True)
    author: Mapped[str | None] = mapped_column(String(255), nullable=True)

    intro: Mapped[str | None] = mapped_column(Text, nullable=True)
    cover_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    category: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str | None] = mapped_column(String(64), nullable=True)

    source_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("book_sources.id", ondelete="CASCADE"), index=True
    )
    source_book_url: Mapped[str] = mapped_column(String(1024))

    word_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latest_chapter: Mapped[str | None] = mapped_column(String(512), nullable=True)

    normalized_name: Mapped[str] = mapped_column(String(512), default="")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ChapterRow(Base):
    """章节表。"""

    __tablename__ = "chapters"
    __table_args__ = (
        UniqueConstraint("book_id", "index", name="uq_chapters_book_index"),
        Index("ix_chapters_book_url", "book_id", "url"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)

    book_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("books.id", ondelete="CASCADE"), index=True
    )

    index: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(512))
    url: Mapped[str] = mapped_column(String(1024))

    is_vip: Mapped[bool] = mapped_column(Boolean, default=False)
    downloaded: Mapped[bool] = mapped_column(Boolean, default=False)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ChapterContentRow(Base):
    """章节正文表。

    正文量最大，单独成表以便按需读取 —— 列出目录时不该把几 MB 正文拉进内存。
    """

    __tablename__ = "chapter_contents"

    chapter_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("chapters.id", ondelete="CASCADE"), primary_key=True
    )

    raw_content: Mapped[str] = mapped_column(Text)
    clean_content: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)

    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class DownloadTaskRow(Base):
    """下载任务表。"""

    __tablename__ = "download_tasks"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    book_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("books.id", ondelete="CASCADE"), index=True
    )

    status: Mapped[str] = mapped_column(String(16), index=True)

    start_chapter: Mapped[int] = mapped_column(Integer)
    end_chapter: Mapped[int] = mapped_column(Integer)

    total: Mapped[int] = mapped_column(Integer, default=0)
    completed: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)

    concurrency: Mapped[int] = mapped_column(Integer, default=4)

    output_format: Mapped[str] = mapped_column(String(16), default="epub")
    output_path: Mapped[str] = mapped_column(String(1024), default="")

    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DownloadTaskItemRow(Base):
    """任务章节明细表。"""

    __tablename__ = "download_task_items"
    __table_args__ = (Index("ix_task_items_task_index", "task_id", "chapter_index"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)

    task_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("download_tasks.id", ondelete="CASCADE"), index=True
    )

    chapter_id: Mapped[str] = mapped_column(String(64))
    chapter_index: Mapped[int] = mapped_column(Integer)
    chapter_name: Mapped[str] = mapped_column(String(512))

    status: Mapped[str] = mapped_column(String(16), default="PENDING")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class HttpCacheRow(Base):
    """HTTP 响应缓存（规划书 §26）。"""

    __tablename__ = "http_cache"

    #: cache key = sha256(method + url + 关键请求头)
    key: Mapped[str] = mapped_column(String(64), primary_key=True)

    url: Mapped[str] = mapped_column(String(2048), index=True)
    method: Mapped[str] = mapped_column(String(8), default="GET")
    status: Mapped[int] = mapped_column(Integer)
    headers: Mapped[str] = mapped_column(Text, default="{}")
    body: Mapped[bytes] = mapped_column(LargeBinary)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # 最近一次命中时间，LRU 淘汰依据
    hit_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    size: Mapped[int] = mapped_column(Integer, default=0)


class SettingRow(Base):
    """键值设置表。"""

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
