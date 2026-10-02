"""FastAPI 依赖注入。

路由通过 ``Annotated`` 取依赖，而不是 import 全局单例 ——
这样测试可以整体替换掉应用状态。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from inkflow_api.services import DownloadTaskManager, LibraryService
from inkflow_api.state import AppState

__all__ = ["LibraryDep", "StateDep", "TasksDep", "get_library", "get_state", "get_tasks"]


def get_state(request: Request) -> AppState:
    """从 ``app.state`` 取应用状态。"""
    state: AppState | None = getattr(request.app.state, "inkflow", None)
    if state is None:  # pragma: no cover - 只在应用装配错误时发生
        raise RuntimeError("应用状态未初始化，请通过 create_app() 构建应用")
    return state


def get_library(state: Annotated[AppState, Depends(get_state)]) -> LibraryService:
    """书库仓储。"""
    return state.library


def get_tasks(state: Annotated[AppState, Depends(get_state)]) -> DownloadTaskManager:
    """下载任务管理器。"""
    return state.tasks


StateDep = Annotated[AppState, Depends(get_state)]
LibraryDep = Annotated[LibraryService, Depends(get_library)]
TasksDep = Annotated[DownloadTaskManager, Depends(get_tasks)]
