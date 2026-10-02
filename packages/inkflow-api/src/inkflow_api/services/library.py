"""书库仓储：领域模型 ↔ SQLite 行 的映射与读写。

持久化模型与领域模型刻意分开。本模块是**唯一**做这层映射的地方，
其他代码只跟 ``inkflow_core.models`` 打交道。
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, func, select

from inkflow_core.errors import ErrorCode, NotFoundError
from inkflow_core.models import (
    Book,
    BookSource,
    Chapter,
    ChapterContent,
    DownloadTask,
    DownloadTaskItem,
    RequestConfig,
    SourceMeta,
)
from inkflow_core.storage import Database
from inkflow_core.storage.tables import (
    BookRow,
    BookSourceRow,
    ChapterContentRow,
    ChapterRow,
    DownloadTaskItemRow,
    DownloadTaskRow,
    SettingRow,
)
from inkflow_core.utils import utcnow

__all__ = ["LibraryService"]


def _ensure_utc(value: datetime | None) -> datetime | None:
    """SQLite 不保存时区，读回来补上 UTC，避免 naive / aware 混用报错。"""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


class LibraryService:
    """书库读写门面。"""

    def __init__(self, db: Database) -> None:
        self.db = db

    # -- 书源 --------------------------------------------------------------

    def save_source(self, source: BookSource) -> BookSource:
        """新增或更新书源。"""
        with self.db.session() as session:
            row = session.get(BookSourceRow, source.id)
            payload = {
                "name": source.name,
                "url": source.url,
                "enabled": source.enabled,
                "priority": source.priority,
                "source_type": str(source.source_type),
                "source_format": str(source.source_format),
                "compatibility_level": str(source.compatibility_level),
                "rule_version": source.rule_version,
                "enabled_search": source.enabled_search,
                "enabled_explore": source.enabled_explore,
                "request_config": source.request.model_dump_json(),
                "meta": source.meta.model_dump_json(),
                "raw": json.dumps(source.raw, ensure_ascii=False),
                "updated_at": utcnow(),
            }
            if row is None:
                session.add(BookSourceRow(id=source.id, created_at=utcnow(), **payload))
            else:
                for key, value in payload.items():
                    setattr(row, key, value)
        return source

    def list_sources(self) -> list[BookSource]:
        """全部书源，按优先级降序。"""
        with self.db.session() as session:
            rows = session.scalars(
                select(BookSourceRow).order_by(BookSourceRow.priority.desc())
            ).all()
            return [_row_to_source(row) for row in rows]

    def get_source(self, source_id: str) -> BookSource:
        """按 ID 取书源。

        Raises:
            NotFoundError: 不存在。
        """
        with self.db.session() as session:
            row = session.get(BookSourceRow, source_id)
            if row is None:
                raise NotFoundError(
                    f"书源不存在: {source_id}",
                    code=ErrorCode.SOURCE_NOT_FOUND,
                    details={"source_id": source_id},
                )
            return _row_to_source(row)

    def delete_source(self, source_id: str) -> bool:
        """删除书源及其关联书籍。返回是否真的删掉了。"""
        with self.db.session() as session:
            row = session.get(BookSourceRow, source_id)
            if row is None:
                return False
            session.delete(row)
            return True

    def set_source_enabled(self, source_id: str, enabled: bool) -> BookSource:
        """启用 / 停用书源。"""
        source = self.get_source(source_id)
        source.enabled = enabled
        source.updated_at = utcnow()
        return self.save_source(source)

    # -- 书籍 --------------------------------------------------------------

    def upsert_book(self, book: Book) -> Book:
        """按 ``(source_id, source_book_url)`` 新增或更新书籍。

        重复导入同一本书时保留既有 ID，因此已下载的章节不会失联。
        """
        with self.db.session() as session:
            existing = session.scalars(
                select(BookRow).where(
                    BookRow.source_id == book.source_id,
                    BookRow.source_book_url == book.source_book_url,
                )
            ).first()

            if existing is not None:
                book.id = existing.id
                existing.name = book.name
                existing.author = book.author
                existing.intro = book.intro
                existing.cover_url = book.cover_url
                existing.category = book.category
                existing.status = book.status
                existing.word_count = book.word_count
                existing.latest_chapter = book.latest_chapter
                existing.normalized_name = book.normalized_name or ""
                existing.updated_at = utcnow()
                return book

            session.add(
                BookRow(
                    id=book.id,
                    name=book.name,
                    author=book.author,
                    intro=book.intro,
                    cover_url=book.cover_url,
                    category=book.category,
                    status=book.status,
                    source_id=book.source_id,
                    source_book_url=book.source_book_url,
                    word_count=book.word_count,
                    latest_chapter=book.latest_chapter,
                    normalized_name=book.normalized_name or "",
                    created_at=book.created_at,
                    updated_at=book.updated_at,
                )
            )
            return book

    def get_book(self, book_id: str) -> Book:
        """按 ID 取书。

        Raises:
            NotFoundError: 不存在。
        """
        with self.db.session() as session:
            row = session.get(BookRow, book_id)
            if row is None:
                raise NotFoundError(
                    f"书籍不存在: {book_id}",
                    code=ErrorCode.BOOK_NOT_FOUND,
                    details={"book_id": book_id},
                )
            return _row_to_book(row)

    def list_books(self, *, limit: int = 50, offset: int = 0) -> list[Book]:
        """按更新时间倒序分页取书。"""
        with self.db.session() as session:
            rows = session.scalars(
                select(BookRow).order_by(BookRow.updated_at.desc()).limit(limit).offset(offset)
            ).all()
            return [_row_to_book(row) for row in rows]

    def count_books(self) -> int:
        with self.db.session() as session:
            return int(session.scalar(select(func.count()).select_from(BookRow)) or 0)

    # -- 章节 --------------------------------------------------------------

    def replace_chapters(self, book_id: str, chapters: list[Chapter]) -> int:
        """整体替换一本书的目录。

        用「全删重插」而不是逐条 upsert：目录抓取是全量的，
        增量合并会残留已被作者删除的章节。

        已下载章节的 ``downloaded`` 与 ``content_hash`` 会被保留 ——
        重新抓目录不该让已下载的正文「掉线」。
        """
        with self.db.session() as session:
            previous = {
                row.index: (row.id, row.downloaded, row.content_hash)
                for row in session.scalars(select(ChapterRow).where(ChapterRow.book_id == book_id))
            }
            session.execute(delete(ChapterRow).where(ChapterRow.book_id == book_id))

            for chapter in chapters:
                old = previous.get(chapter.index)
                if old is not None and old[2] == chapter.content_hash:
                    chapter.downloaded = old[1]
                session.add(
                    ChapterRow(
                        id=chapter.id,
                        book_id=book_id,
                        index=chapter.index,
                        name=chapter.name,
                        url=chapter.url,
                        is_vip=chapter.is_vip,
                        downloaded=chapter.downloaded,
                        content_hash=chapter.content_hash,
                        created_at=chapter.created_at,
                        updated_at=chapter.updated_at,
                    )
                )
            return len(chapters)

    def get_chapters(self, book_id: str) -> list[Chapter]:
        """按 index 升序取目录。"""
        with self.db.session() as session:
            rows = session.scalars(
                select(ChapterRow).where(ChapterRow.book_id == book_id).order_by(ChapterRow.index)
            ).all()
            return [_row_to_chapter(row) for row in rows]

    def get_chapter(self, chapter_id: str) -> Chapter:
        """按 ID 取章节。

        Raises:
            NotFoundError: 不存在。
        """
        with self.db.session() as session:
            row = session.get(ChapterRow, chapter_id)
            if row is None:
                raise NotFoundError(
                    f"章节不存在: {chapter_id}",
                    details={"chapter_id": chapter_id},
                )
            return _row_to_chapter(row)

    def mark_chapter_downloaded(self, chapter_id: str, content_hash: str) -> None:
        """标记章节已下载。"""
        with self.db.session() as session:
            row = session.get(ChapterRow, chapter_id)
            if row is None:
                return
            row.downloaded = True
            row.content_hash = content_hash
            row.updated_at = utcnow()

    # -- 正文 --------------------------------------------------------------

    def save_content(self, content: ChapterContent) -> None:
        """写入或更新章节正文。"""
        with self.db.session() as session:
            row = session.get(ChapterContentRow, content.chapter_id)
            if row is None:
                session.add(
                    ChapterContentRow(
                        chapter_id=content.chapter_id,
                        raw_content=content.raw_content,
                        clean_content=content.clean_content,
                        content_hash=content.content_hash,
                        fetched_at=content.fetched_at,
                    )
                )
            else:
                row.raw_content = content.raw_content
                row.clean_content = content.clean_content
                row.content_hash = content.content_hash
                row.fetched_at = content.fetched_at

    def get_content(self, chapter_id: str) -> ChapterContent | None:
        """取章节正文，未下载返回 ``None``。"""
        with self.db.session() as session:
            row = session.get(ChapterContentRow, chapter_id)
            if row is None:
                return None
            return ChapterContent(
                chapter_id=row.chapter_id,
                raw_content=row.raw_content,
                clean_content=row.clean_content,
                content_hash=row.content_hash,
                fetched_at=_ensure_utc(row.fetched_at) or utcnow(),
            )

    def get_contents(self, chapter_ids: list[str]) -> dict[str, ChapterContent]:
        """批量取正文，避免导出时逐章查询。"""
        if not chapter_ids:
            return {}
        with self.db.session() as session:
            rows = session.scalars(
                select(ChapterContentRow).where(ChapterContentRow.chapter_id.in_(chapter_ids))
            ).all()
            return {
                row.chapter_id: ChapterContent(
                    chapter_id=row.chapter_id,
                    raw_content=row.raw_content,
                    clean_content=row.clean_content,
                    content_hash=row.content_hash,
                    fetched_at=_ensure_utc(row.fetched_at) or utcnow(),
                )
                for row in rows
            }

    # -- 任务 --------------------------------------------------------------

    def save_task(self, task: DownloadTask) -> None:
        """写入或更新任务。"""
        with self.db.session() as session:
            row = session.get(DownloadTaskRow, task.id)
            payload: dict[str, Any] = {
                "book_id": task.book_id,
                "status": str(task.status),
                "start_chapter": task.start_chapter,
                "end_chapter": task.end_chapter,
                "total": task.total,
                "completed": task.completed,
                "failed": task.failed,
                "concurrency": task.concurrency,
                "output_format": task.output_format,
                "output_path": task.output_path,
                "error": task.error,
                "started_at": task.started_at,
                "finished_at": task.finished_at,
            }
            if row is None:
                session.add(DownloadTaskRow(id=task.id, created_at=task.created_at, **payload))
            else:
                for key, value in payload.items():
                    setattr(row, key, value)

    def get_task(self, task_id: str) -> DownloadTask:
        """按 ID 取任务。

        Raises:
            NotFoundError: 不存在。
        """
        with self.db.session() as session:
            row = session.get(DownloadTaskRow, task_id)
            if row is None:
                raise NotFoundError(
                    f"任务不存在: {task_id}",
                    code=ErrorCode.TASK_NOT_FOUND,
                    details={"task_id": task_id},
                )
            return _row_to_task(row)

    def list_tasks(self, *, limit: int = 100) -> list[DownloadTask]:
        """按创建时间倒序取任务。"""
        with self.db.session() as session:
            rows = session.scalars(
                select(DownloadTaskRow).order_by(DownloadTaskRow.created_at.desc()).limit(limit)
            ).all()
            return [_row_to_task(row) for row in rows]

    def save_task_items(self, items: list[DownloadTaskItem]) -> None:
        """写入任务章节明细。"""
        if not items:
            return
        with self.db.session() as session:
            for item in items:
                row = session.get(DownloadTaskItemRow, item.id)
                payload = {
                    "task_id": item.task_id,
                    "chapter_id": item.chapter_id,
                    "chapter_index": item.chapter_index,
                    "chapter_name": item.chapter_name,
                    "status": str(item.status),
                    "attempts": item.attempts,
                    "error": item.error,
                    "started_at": item.started_at,
                    "finished_at": item.finished_at,
                }
                if row is None:
                    session.add(DownloadTaskItemRow(id=item.id, **payload))
                else:
                    for key, value in payload.items():
                        setattr(row, key, value)

    def get_task_items(self, task_id: str) -> list[DownloadTaskItem]:
        """按章节顺序取任务明细。"""
        with self.db.session() as session:
            rows = session.scalars(
                select(DownloadTaskItemRow)
                .where(DownloadTaskItemRow.task_id == task_id)
                .order_by(DownloadTaskItemRow.chapter_index)
            ).all()
            return [
                DownloadTaskItem(
                    id=row.id,
                    task_id=row.task_id,
                    chapter_id=row.chapter_id,
                    chapter_index=row.chapter_index,
                    chapter_name=row.chapter_name,
                    status=row.status,  # type: ignore[arg-type]
                    attempts=row.attempts,
                    error=row.error,
                    started_at=_ensure_utc(row.started_at),
                    finished_at=_ensure_utc(row.finished_at),
                )
                for row in rows
            ]

    # -- 设置 --------------------------------------------------------------

    def get_setting(self, key: str, default: str | None = None) -> str | None:
        """读设置项。"""
        with self.db.session() as session:
            row = session.get(SettingRow, key)
            return row.value if row is not None else default

    def set_setting(self, key: str, value: str) -> None:
        """写设置项。"""
        with self.db.session() as session:
            row = session.get(SettingRow, key)
            if row is None:
                session.add(SettingRow(key=key, value=value, updated_at=utcnow()))
            else:
                row.value = value
                row.updated_at = utcnow()

    def all_settings(self) -> dict[str, str]:
        """全部设置项。"""
        with self.db.session() as session:
            rows = session.scalars(select(SettingRow)).all()
            return {row.key: row.value for row in rows}


# ---------------------------------------------------------------- 行 → 模型


def _row_to_source(row: BookSourceRow) -> BookSource:
    return BookSource.model_validate(
        {
            "id": row.id,
            "name": row.name,
            "url": row.url,
            "enabled": row.enabled,
            "priority": row.priority,
            "source_type": row.source_type,
            "source_format": row.source_format,
            "compatibility_level": row.compatibility_level,
            "rule_version": row.rule_version,
            "enabled_search": row.enabled_search,
            "enabled_explore": row.enabled_explore,
            "request": _loads(row.request_config, RequestConfig().model_dump()),
            "meta": _loads(row.meta, SourceMeta().model_dump()),
            "raw": _loads(row.raw, {}),
            "created_at": _ensure_utc(row.created_at),
            "updated_at": _ensure_utc(row.updated_at),
        }
    )


def _row_to_book(row: BookRow) -> Book:
    return Book(
        id=row.id,
        name=row.name,
        author=row.author,
        intro=row.intro,
        cover_url=row.cover_url,
        category=row.category,
        status=row.status,
        source_id=row.source_id,
        source_book_url=row.source_book_url,
        word_count=row.word_count,
        latest_chapter=row.latest_chapter,
        normalized_name=row.normalized_name,
        created_at=_ensure_utc(row.created_at) or utcnow(),
        updated_at=_ensure_utc(row.updated_at) or utcnow(),
    )


def _row_to_chapter(row: ChapterRow) -> Chapter:
    return Chapter(
        id=row.id,
        book_id=row.book_id,
        index=row.index,
        name=row.name,
        url=row.url,
        is_vip=row.is_vip,
        downloaded=row.downloaded,
        content_hash=row.content_hash,
        created_at=_ensure_utc(row.created_at) or utcnow(),
        updated_at=_ensure_utc(row.updated_at) or utcnow(),
    )


def _row_to_task(row: DownloadTaskRow) -> DownloadTask:
    return DownloadTask(
        id=row.id,
        book_id=row.book_id,
        status=row.status,  # type: ignore[arg-type]
        start_chapter=row.start_chapter,
        end_chapter=row.end_chapter,
        total=row.total,
        completed=row.completed,
        failed=row.failed,
        concurrency=row.concurrency,
        output_format=row.output_format,
        output_path=row.output_path,
        error=row.error,
        created_at=_ensure_utc(row.created_at) or utcnow(),
        started_at=_ensure_utc(row.started_at),
        finished_at=_ensure_utc(row.finished_at),
    )


def _loads(text: str | None, default: Any) -> Any:
    """容错 JSON 解析：损坏的字段退回默认值，不让整个列表接口挂掉。"""
    if not text:
        return default
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return default
