"""下载任务路由（规划书 §27.6）。"""

from __future__ import annotations

from fastapi import APIRouter

from inkflow_api.deps import StateDep
from inkflow_api.schemas import (
    TaskCreateRequest,
    TaskDetailResponse,
    TaskItemsResponse,
    TaskListResponse,
)
from inkflow_core.errors import NotFoundError
from inkflow_core.models import DownloadTask

__all__ = ["router"]

router = APIRouter(prefix="/api/v1/tasks", tags=["tasks"])


@router.post("", response_model=DownloadTask, summary="创建下载任务", status_code=201)
async def create_task(state: StateDep, payload: TaskCreateRequest) -> DownloadTask:
    """创建下载任务并（默认）立即启动。

    章节区间为闭区间；``end_chapter`` 省略时下载到最后一章。

    Raises:
        NotFoundError: 书籍不存在。
        SourceError: 该书还没有目录。
    """
    return await state.tasks.create_task(
        payload.book_id,
        start_chapter=payload.start_chapter,
        end_chapter=payload.end_chapter,
        concurrency=payload.concurrency,
        output_format=payload.output_format,
        output_path=payload.output_path,
        auto_start=payload.auto_start,
    )


@router.get("", response_model=TaskListResponse, summary="任务列表")
async def list_tasks(state: StateDep) -> TaskListResponse:
    """按创建时间倒序列出任务。"""
    items = state.tasks.list_tasks()
    return TaskListResponse(items=items, total=len(items))


@router.get("/{task_id}", response_model=TaskDetailResponse, summary="任务详情")
async def get_task(state: StateDep, task_id: str) -> TaskDetailResponse:
    """任务详情，含所属书籍信息。

    Raises:
        NotFoundError: 任务不存在。
    """
    task = state.tasks.get(task_id)
    book = None
    try:
        book = state.library.get_book(task.book_id)
    except NotFoundError:
        book = None
    return TaskDetailResponse(task=task, book=book)


@router.get("/{task_id}/items", response_model=TaskItemsResponse, summary="任务章节明细")
async def get_task_items(state: StateDep, task_id: str) -> TaskItemsResponse:
    """逐章状态，用于展示失败章节与重试次数。"""
    items = state.library.get_task_items(task_id)
    return TaskItemsResponse(
        task_id=task_id,
        items=[item.model_dump(mode="json") for item in items],
        total=len(items),
    )


@router.post("/{task_id}/pause", response_model=DownloadTask, summary="暂停任务")
async def pause_task(state: StateDep, task_id: str) -> DownloadTask:
    """暂停任务。

    已在途的章节会跑完，但不会开始新章节 —— 已下载的内容全部保留。

    Raises:
        InkFlowError: 任务不在运行中。
    """
    return await state.tasks.pause(task_id)


@router.post("/{task_id}/resume", response_model=DownloadTask, summary="恢复任务")
async def resume_task(state: StateDep, task_id: str) -> DownloadTask:
    """恢复已暂停的任务。

    Raises:
        InkFlowError: 任务不在暂停状态。
    """
    return await state.tasks.resume(task_id)


@router.post("/{task_id}/cancel", response_model=DownloadTask, summary="取消任务")
async def cancel_task(state: StateDep, task_id: str) -> DownloadTask:
    """取消任务。已下载的章节保留，任务不再继续。"""
    return await state.tasks.cancel(task_id)
