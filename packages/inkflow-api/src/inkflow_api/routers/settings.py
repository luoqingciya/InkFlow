"""设置路由（规划书 §52）。

只暴露**白名单内**的可调项。``server.host``、``js.enabled`` 这类
与安全边界相关的配置不允许通过 HTTP 修改 —— 否则一次误操作就能把
本地服务暴露到局域网。
"""

from __future__ import annotations

from fastapi import APIRouter

from inkflow_api.deps import StateDep
from inkflow_api.schemas import SettingsResponse, SettingsUpdateRequest

__all__ = ["router"]

router = APIRouter(prefix="/api/v1/settings", tags=["settings"])


def _snapshot(state: StateDep) -> SettingsResponse:
    """把配置转成响应体。"""
    settings = state.settings
    return SettingsResponse(
        server=settings.server.model_dump(),
        download=settings.download.model_dump(),
        export=settings.export.model_dump(),
        cache=settings.cache.model_dump(),
        source=settings.source.model_dump(),
        js=settings.js.model_dump(),
        browser=settings.browser.model_dump(),
        log=settings.log.model_dump(),
    )


@router.get("", response_model=SettingsResponse, summary="读取设置")
async def get_settings(state: StateDep) -> SettingsResponse:
    """返回当前生效的配置。"""
    return _snapshot(state)


@router.patch("", response_model=SettingsResponse, summary="更新设置")
async def update_settings(state: StateDep, payload: SettingsUpdateRequest) -> SettingsResponse:
    """更新设置。

    改动**立即生效于进程内**，但不会写回 ``config.toml`` ——
    重启后恢复文件中的值。需要持久化请直接改配置文件。
    """
    settings = state.settings

    if payload.default_export_format is not None:
        settings.export.default_format = payload.default_export_format.lower()
    if payload.download_concurrency is not None:
        settings.download.concurrency = payload.download_concurrency
    if payload.download_timeout is not None:
        settings.download.timeout = payload.download_timeout
    if payload.cache_enabled is not None:
        settings.cache.enabled = payload.cache_enabled
    if payload.source_allow_private_network is not None:
        settings.source.allow_private_network = payload.source_allow_private_network

    # 记录到数据库，便于 UI 展示「上次修改」
    state.library.set_setting("settings.updated_by_api", "1")
    return _snapshot(state)
