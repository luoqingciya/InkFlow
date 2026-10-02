"""WebSocket 进度通道（规划书 §28）。

轮询 REST 也能拿到进度，但下载是秒级变化的事件流 —— 轮询要么太慢
（进度条卡顿），要么太密（无谓请求）。WebSocket 只推变化。

鉴权走查询参数 ``?token=``，因为浏览器的 WebSocket API 不支持自定义请求头。
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from inkflow_core.errors import InkFlowError
from inkflow_core.models import TaskStatus

__all__ = ["router"]

router = APIRouter(tags=["websocket"])

#: 空闲多久发送一次心跳（秒）。防止中间设备把空闲连接掐断。
HEARTBEAT_INTERVAL = 20.0


@router.websocket("/ws/tasks/{task_id}")
async def task_progress(websocket: WebSocket, task_id: str) -> None:
    """推送单个任务的进度事件。

    连接建立后先发一条 ``snapshot``（当前状态），随后按事件推送。
    任务进入终态时服务端主动关闭连接。
    """
    state = getattr(websocket.app.state, "inkflow", None)
    if state is None:  # pragma: no cover
        await websocket.close(code=1011)
        return

    await websocket.accept()

    try:
        task = state.tasks.get(task_id)
    except InkFlowError:
        await websocket.send_json(
            {"type": "error", "code": "TASK_NOT_FOUND", "message": f"任务不存在: {task_id}"}
        )
        await websocket.close(code=4404)
        return

    await websocket.send_json(
        {
            "type": "snapshot",
            "task_id": task_id,
            "status": str(task.status),
            "completed": task.completed,
            "failed": task.failed,
            "total": task.total,
            "percent": round(task.progress * 100, 1),
            "speed": f"{task.chapters_per_second:.2f} ch/s",
        }
    )

    if task.status.is_terminal:
        await websocket.close(code=1000)
        return

    queue = state.tasks.subscribe(task_id)
    try:
        while True:
            try:
                event: dict[str, Any] = await asyncio.wait_for(
                    queue.get(), timeout=HEARTBEAT_INTERVAL
                )
            except TimeoutError:
                await websocket.send_json({"type": "heartbeat", "task_id": task_id})
                continue

            await websocket.send_json(event)

            status = str(event.get("status", ""))
            if event.get("type") in {"completed", "error"} or status in {
                str(TaskStatus.COMPLETED),
                str(TaskStatus.FAILED),
                str(TaskStatus.CANCELLED),
            }:
                break

    except WebSocketDisconnect:
        # 客户端主动断开是正常情况，不需要记错误
        pass
    finally:
        state.tasks.unsubscribe(task_id, queue)
        # 客户端可能已经断开，此时 close 会抛 RuntimeError，属正常情况
        with contextlib.suppress(RuntimeError):
            await websocket.close(code=1000)
