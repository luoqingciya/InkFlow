"""下载任务管理（规划书 §14、§15）。

    DownloadTask
         ↓
    TaskScheduler
         ↓
    Worker Pool        （并发受全局 / 域名 / 书源三级约束）
         ↓
    Chapter Downloader
         ↓
    Normalizer         （由适配器内部完成）
         ↓
    Storage
         ↓
    Exporter

关键设计：

* 任务状态机在领域层（``DownloadTask.transition_to``），非法转换直接被拒。
* 暂停用 ``asyncio.Event`` 而非取消协程 —— 取消会丢掉已经拿到的正文。
* 单章失败**不中断**整个任务，只累计 ``failed`` 并记录到明细表。
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from inkflow_api.services.library import LibraryService
from inkflow_core.config import Settings
from inkflow_core.errors import ErrorCode, InkFlowError, SourceError
from inkflow_core.models import (
    Book,
    Chapter,
    ChapterContent,
    DownloadTask,
    DownloadTaskItem,
    TaskItemStatus,
    TaskStatus,
)
from inkflow_core.paths import InkFlowPaths
from inkflow_core.utils import new_task_id, new_task_item_id, utcnow
from inkflow_source.registry import SourceRegistry

__all__ = ["DownloadTaskManager", "ProgressBroker"]


class ProgressBroker:
    """任务进度事件广播。

    WebSocket 只是订阅者之一 —— 将来加 SSE、日志落盘、桌面通知都接这里，
    不需要改下载器。
    """

    def __init__(self) -> None:
        self._subscribers: dict[str, set[asyncio.Queue[dict[str, Any]]]] = {}

    def subscribe(self, task_id: str, *, maxsize: int = 256) -> asyncio.Queue[dict[str, Any]]:
        """订阅某个任务的进度事件。"""
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=maxsize)
        self._subscribers.setdefault(task_id, set()).add(queue)
        return queue

    def unsubscribe(self, task_id: str, queue: asyncio.Queue[dict[str, Any]]) -> None:
        """取消订阅。"""
        subscribers = self._subscribers.get(task_id)
        if not subscribers:
            return
        subscribers.discard(queue)
        if not subscribers:
            self._subscribers.pop(task_id, None)

    def publish(self, task_id: str, event: dict[str, Any]) -> None:
        """广播事件。

        队列满时**丢弃最旧**的事件而不是阻塞下载器 ——
        进度是快照型数据，落后的事件没有价值。
        """
        for queue in list(self._subscribers.get(task_id, ())):
            if queue.full():
                with contextlib.suppress(asyncio.QueueEmpty):
                    queue.get_nowait()
            with contextlib.suppress(asyncio.QueueFull):
                queue.put_nowait(event)

    def subscriber_count(self, task_id: str) -> int:
        return len(self._subscribers.get(task_id, ()))


class DownloadTaskManager:
    """创建、调度与追踪下载任务。"""

    def __init__(
        self,
        *,
        registry: SourceRegistry,
        library: LibraryService,
        settings: Settings,
        paths: InkFlowPaths,
    ) -> None:
        self.registry = registry
        self.library = library
        self.settings = settings
        self.paths = paths
        self.broker = ProgressBroker()

        self._runners: dict[str, asyncio.Task[None]] = {}
        self._pause_events: dict[str, asyncio.Event] = {}
        self._cancel_flags: dict[str, bool] = {}

    # -- 创建与查询 --------------------------------------------------------

    async def create_task(
        self,
        book_id: str,
        *,
        start_chapter: int = 0,
        end_chapter: int | None = None,
        concurrency: int | None = None,
        output_format: str | None = None,
        output_path: str | None = None,
        auto_start: bool = True,
    ) -> DownloadTask:
        """创建下载任务。

        Raises:
            NotFoundError: 书籍不存在。
            SourceError: 目录为空。
        """
        book = self.library.get_book(book_id)
        chapters = self.library.get_chapters(book_id)
        if not chapters:
            raise SourceError(
                "该书还没有目录，请先获取目录",
                code=ErrorCode.BOOK_NO_CHAPTERS,
                details={"book_id": book_id},
            )

        last_index = len(chapters) - 1
        start = max(0, min(start_chapter, last_index))
        end = last_index if end_chapter is None else max(start, min(end_chapter, last_index))
        selected = [c for c in chapters if start <= c.index <= end]

        fmt = (output_format or self.settings.export.default_format).lower()
        task = DownloadTask(
            id=new_task_id(),
            book_id=book_id,
            start_chapter=start,
            end_chapter=end,
            total=len(selected),
            concurrency=concurrency or self.settings.download.concurrency,
            output_format=fmt,
            output_path=output_path or str(self._default_output_path(book, fmt)),
        )
        self.library.save_task(task)
        self.library.save_task_items(
            [
                DownloadTaskItem(
                    id=new_task_item_id(),
                    task_id=task.id,
                    chapter_id=chapter.id,
                    chapter_index=chapter.index,
                    chapter_name=chapter.name,
                )
                for chapter in selected
            ]
        )

        if auto_start:
            await self.start(task.id)
        return task

    def get(self, task_id: str) -> DownloadTask:
        """取任务（含实时进度）。"""
        return self.library.get_task(task_id)

    def list_tasks(self, *, limit: int = 100) -> list[DownloadTask]:
        """列出任务。"""
        return self.library.list_tasks(limit=limit)

    def is_running(self, task_id: str) -> bool:
        runner = self._runners.get(task_id)
        return runner is not None and not runner.done()

    # -- 生命周期 ----------------------------------------------------------

    async def start(self, task_id: str) -> DownloadTask:
        """启动任务（幂等：已在运行则原样返回）。"""
        task = self.library.get_task(task_id)
        if self.is_running(task_id):
            return task
        if task.status.is_terminal:
            raise InkFlowError(
                f"任务已处于终态 {task.status}，无法启动",
                code=ErrorCode.TASK_INVALID_STATE,
                details={"task_id": task_id, "status": str(task.status)},
                status_code=409,
            )

        self._cancel_flags[task_id] = False
        self._pause_events.setdefault(task_id, asyncio.Event())
        self._pause_events[task_id].set()

        task.transition_to(TaskStatus.RUNNING)
        self.library.save_task(task)

        self._runners[task_id] = asyncio.create_task(self._run(task_id))
        return task

    async def pause(self, task_id: str) -> DownloadTask:
        """暂停任务。已下载的章节会保留。"""
        task = self.library.get_task(task_id)
        if task.status is not TaskStatus.RUNNING:
            raise InkFlowError(
                f"只有运行中的任务可以暂停（当前 {task.status}）",
                code=ErrorCode.TASK_INVALID_STATE,
                details={"task_id": task_id, "status": str(task.status)},
                status_code=409,
            )
        event = self._pause_events.get(task_id)
        if event is not None:
            event.clear()
        task.transition_to(TaskStatus.PAUSED)
        self.library.save_task(task)
        self.broker.publish(task_id, {"type": "status", "status": str(task.status)})
        return task

    async def resume(self, task_id: str) -> DownloadTask:
        """恢复任务。"""
        task = self.library.get_task(task_id)
        if task.status is not TaskStatus.PAUSED:
            raise InkFlowError(
                f"只有已暂停的任务可以恢复（当前 {task.status}）",
                code=ErrorCode.TASK_INVALID_STATE,
                details={"task_id": task_id, "status": str(task.status)},
                status_code=409,
            )
        if not self.is_running(task_id):
            # 进程重启后 runner 已丢失，重新拉起
            task.status = TaskStatus.PENDING
            self.library.save_task(task)
            return await self.start(task_id)

        event = self._pause_events.setdefault(task_id, asyncio.Event())
        event.set()
        task.transition_to(TaskStatus.RUNNING)
        self.library.save_task(task)
        self.broker.publish(task_id, {"type": "status", "status": str(task.status)})
        return task

    async def cancel(self, task_id: str) -> DownloadTask:
        """取消任务。"""
        task = self.library.get_task(task_id)
        if task.status.is_terminal:
            return task

        self._cancel_flags[task_id] = True
        event = self._pause_events.get(task_id)
        if event is not None:
            event.set()  # 让阻塞在暂停点的 worker 醒过来并看到取消标记

        runner = self._runners.get(task_id)
        if runner is not None and not runner.done():
            with contextlib.suppress(asyncio.CancelledError, TimeoutError):
                await asyncio.wait_for(asyncio.shield(runner), timeout=5.0)

        task = self.library.get_task(task_id)
        if not task.status.is_terminal:
            task.transition_to(TaskStatus.CANCELLED)
            self.library.save_task(task)
        self.broker.publish(task_id, {"type": "status", "status": str(task.status)})
        return task

    def subscribe(self, task_id: str) -> asyncio.Queue[dict[str, Any]]:
        """订阅任务进度。"""
        return self.broker.subscribe(task_id)

    def unsubscribe(self, task_id: str, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self.broker.unsubscribe(task_id, queue)

    async def shutdown(self) -> None:
        """关闭全部运行中的任务（服务退出时调用）。"""
        for task_id in list(self._runners):
            with contextlib.suppress(Exception):
                await self.cancel(task_id)
        self._runners.clear()
        self._pause_events.clear()
        self._cancel_flags.clear()

    # -- 执行 --------------------------------------------------------------

    async def _run(self, task_id: str) -> None:
        """任务主循环。"""
        try:
            await self._execute(task_id)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            task = self.library.get_task(task_id)
            if not task.status.is_terminal:
                task.error = f"{type(exc).__name__}: {exc}"
                task.transition_to(TaskStatus.FAILED)
                self.library.save_task(task)
            self.broker.publish(
                task_id,
                {"type": "error", "message": str(exc), "status": str(TaskStatus.FAILED)},
            )
        finally:
            self._runners.pop(task_id, None)

    async def _execute(self, task_id: str) -> None:
        """按章节并发下载。"""
        task = self.library.get_task(task_id)
        book = self.library.get_book(task.book_id)
        chapters = [
            c
            for c in self.library.get_chapters(task.book_id)
            if task.start_chapter <= c.index <= task.end_chapter
        ]
        items = {item.chapter_index: item for item in self.library.get_task_items(task_id)}
        adapter = self.registry.get(book.source_id)

        semaphore = asyncio.Semaphore(task.concurrency)
        pause_event = self._pause_events.setdefault(task_id, asyncio.Event())
        pause_event.set()

        # 已下载过的章节直接跳过，恢复任务时不重复抓取
        pending = [
            chapter
            for chapter in chapters
            if not (chapter.downloaded and self.library.get_content(chapter.id))
        ]
        skipped = len(chapters) - len(pending)
        if skipped:
            task.completed += skipped
            self.library.save_task(task)
            self.broker.publish(
                task_id,
                {
                    "type": "progress",
                    "completed": task.completed,
                    "total": task.total,
                    "message": f"跳过 {skipped} 个已下载章节",
                },
            )

        async def worker(chapter: Chapter) -> None:
            if self._cancel_flags.get(task_id):
                return
            await pause_event.wait()
            if self._cancel_flags.get(task_id):
                return

            item = items.get(chapter.index)
            async with semaphore:
                await self._download_chapter(task_id, book, chapter, item, adapter)

        try:
            await asyncio.gather(*(worker(chapter) for chapter in pending))
        except asyncio.CancelledError:
            raise

        task = self.library.get_task(task_id)
        if self._cancel_flags.get(task_id):
            task.transition_to(TaskStatus.CANCELLED)
            self.library.save_task(task)
            self.broker.publish(task_id, {"type": "status", "status": str(TaskStatus.CANCELLED)})
            return

        # 暂停状态下不要标记完成
        if task.status is TaskStatus.PAUSED:
            return

        task.transition_to(TaskStatus.COMPLETED)
        self.library.save_task(task)

        if task.output_format:
            await self._export(task)

        self.broker.publish(
            task_id,
            {
                "type": "completed",
                "completed": task.completed,
                "failed": task.failed,
                "total": task.total,
                "output_path": task.output_path,
                "status": str(TaskStatus.COMPLETED),
            },
        )

    async def _download_chapter(
        self,
        task_id: str,
        book: Book,
        chapter: Chapter,
        item: DownloadTaskItem | None,
        adapter: Any,
    ) -> None:
        """下载单章。失败只累计计数，不抛出。"""
        if item is not None:
            item.status = TaskItemStatus.RUNNING
            item.attempts += 1
            item.started_at = utcnow()
            self.library.save_task_items([item])

        try:
            result = await adapter.content(chapter.url)
            content = ChapterContent(
                chapter_id=chapter.id,
                raw_content=result.raw or result.content,
                clean_content=result.content,
                content_hash="",
            )
            self.library.save_content(content)
            self.library.mark_chapter_downloaded(chapter.id, content.content_hash)

            if item is not None:
                item.status = TaskItemStatus.SUCCESS
                item.finished_at = utcnow()
                self.library.save_task_items([item])

            task = self.library.get_task(task_id)
            task.completed += 1
            self.library.save_task(task)
            self._publish_progress(task, chapter)

        except Exception as exc:
            if item is not None:
                item.status = TaskItemStatus.FAILED
                item.error = f"{type(exc).__name__}: {exc}"
                item.finished_at = utcnow()
                self.library.save_task_items([item])

            task = self.library.get_task(task_id)
            task.failed += 1
            self.library.save_task(task)
            self._publish_progress(task, chapter, error=str(exc))

    def _publish_progress(
        self, task: DownloadTask, chapter: Chapter, *, error: str | None = None
    ) -> None:
        """推送进度事件。"""
        event: dict[str, Any] = {
            "type": "progress",
            "completed": task.completed,
            "failed": task.failed,
            "total": task.total,
            "current": chapter.name,
            "index": chapter.index,
            "percent": round(task.progress * 100, 1),
            "speed": f"{task.chapters_per_second:.2f} ch/s",
        }
        if error:
            event["error"] = error
        self.broker.publish(task.id, event)

    async def _export(self, task: DownloadTask) -> None:
        """任务完成后导出。"""
        from inkflow_export import ExportChapter, ExportRequest, get_exporter

        book = self.library.get_book(task.book_id)
        chapters = [
            c
            for c in self.library.get_chapters(task.book_id)
            if task.start_chapter <= c.index <= task.end_chapter
        ]
        contents = self.library.get_contents([c.id for c in chapters])

        try:
            exporter = get_exporter(task.output_format)
        except ValueError as exc:
            task.error = str(exc)
            self.library.save_task(task)
            return

        output_path = Path(task.output_path)
        if output_path.suffix.lower() != exporter.extension:
            output_path = output_path.with_suffix(exporter.extension)

        source_name = ""
        with contextlib.suppress(Exception):
            source_name = self.library.get_source(book.source_id).name

        request = ExportRequest(
            book=book,
            chapters=[ExportChapter(chapter=c, content=contents.get(c.id)) for c in chapters],
            output_path=output_path,
            source_name=source_name,
        )
        written = await asyncio.to_thread(exporter.export, request)

        task.output_path = str(written)
        self.library.save_task(task)

    def _default_output_path(self, book: Book, fmt: str) -> Path:
        """默认导出路径：``~/.inkflow/exports/<书名>.<扩展名>``。"""
        from inkflow_export import get_exporter, sanitize_filename

        try:
            extension = get_exporter(fmt).extension
        except ValueError:
            extension = f".{fmt}"

        base = self.settings.export.default_output_dir
        directory = Path(base) if base else self.paths.exports_dir
        return directory / f"{sanitize_filename(book.name)}{extension}"


async def iter_events(manager: DownloadTaskManager, task_id: str) -> AsyncIterator[dict[str, Any]]:
    """把订阅队列包装成异步迭代器，便于 WebSocket 直接消费。"""
    queue = manager.subscribe(task_id)
    try:
        while True:
            yield await queue.get()
    finally:
        manager.unsubscribe(task_id, queue)
