"""系统路由：健康检查与运行概况。"""

from __future__ import annotations

from fastapi import APIRouter

from inkflow_api.deps import StateDep
from inkflow_api.schemas import HealthResponse, SystemInfoResponse
from inkflow_core import __version__

__all__ = ["router"]

router = APIRouter(tags=["system"])


@router.get("/health", response_model=HealthResponse, summary="健康检查")
async def health(state: StateDep) -> HealthResponse:
    """就绪探测。

    Desktop 启动后端后轮询这里；**必须免鉴权**，
    否则启动流程会卡在「拿不到 token 就探不到健康」的死循环。
    """
    return HealthResponse(
        status="ok",
        version=__version__,
        uptime_seconds=round(state.uptime_seconds, 2),
    )


@router.get("/api/v1/system/info", response_model=SystemInfoResponse, summary="运行概况")
async def system_info(state: StateDep) -> SystemInfoResponse:
    """返回书源 / 书籍 / 任务的统计与运行环境信息。"""
    return SystemInfoResponse(**state.system_info())  # type: ignore[arg-type]
