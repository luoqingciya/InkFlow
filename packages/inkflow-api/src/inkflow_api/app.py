"""FastAPI 应用工厂。

用工厂函数而不是模块级 ``app = FastAPI()``，是为了让测试可以注入
临时目录与内存数据库 —— 模块级单例做不到这一点。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from inkflow_api.auth import TokenAuthMiddleware
from inkflow_api.errors import install_error_handlers
from inkflow_api.routers import books, search, sources, system, tasks, ws
from inkflow_api.routers import settings as settings_router
from inkflow_api.state import AppState, build_state
from inkflow_core import __version__
from inkflow_core.config import Settings
from inkflow_core.utils import new_trace_id

__all__ = ["create_app"]

DESCRIPTION = """\
InkFlow —— API-First 小说资源聚合与下载平台。

* **CLI 和 Desktop 都只是客户端**，业务核心只有一份。
* **内核兼容 + 外层隔离**：Legado 书源支持被关在独立的兼容层里。
* **书源是不可信输入**：JS 沙箱、SSRF 防护、资源限额默认开启。
"""


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """启动时加载书源，关闭时优雅停机。"""
    state: AppState = app.state.inkflow
    _load_persisted_sources(state)
    try:
        yield
    finally:
        await state.shutdown()


def _load_persisted_sources(state: AppState) -> None:
    """把数据库中已启用的书源注册进注册表。

    书源定义持久化在 SQLite 里，但适配器实例是内存对象 ——
    每次启动都要重建。单个书源构造失败不应阻止服务启动。
    """
    import logging

    logger = logging.getLogger("inkflow.api")
    for source in state.library.list_sources():
        if not source.enabled:
            continue
        try:
            state.registry.create(source, replace=True)
        except Exception as exc:
            logger.warning("书源 %s(%s) 加载失败：%s", source.name, source.id, exc)


def create_app(
    settings: Settings | None = None,
    *,
    state: AppState | None = None,
    require_token: bool | None = None,
    **state_kwargs: object,
) -> FastAPI:
    """构建 FastAPI 应用。

    Args:
        settings: 配置对象。
        state: 直接注入已构建的状态（测试用）。
        require_token: 覆盖 ``server.require_token``；``None`` 表示按配置走。
        **state_kwargs: 透传给 ``build_state`` 的参数，
            如 ``database_url="sqlite:///:memory:"``。

    Returns:
        配置完毕的 ``FastAPI`` 实例。
    """
    resolved = state or build_state(settings, **state_kwargs)  # type: ignore[arg-type]

    app = FastAPI(
        title="InkFlow API",
        description=DESCRIPTION,
        version=__version__,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )
    app.state.inkflow = resolved

    install_error_handlers(app)

    # 中间件顺序：后添加的先执行。鉴权在内，trace 在外 ——
    # 这样 401 响应也带 trace_id。
    token_enabled = (
        resolved.settings.server.require_token if require_token is None else require_token
    )
    app.add_middleware(
        TokenAuthMiddleware,
        token=resolved.session_token,
        enabled=token_enabled,
    )

    @app.middleware("http")
    async def _trace(request, call_next):  # type: ignore[no-untyped-def]
        trace_id = request.headers.get("x-trace-id") or new_trace_id()
        request.state.trace_id = trace_id
        response = await call_next(request)
        response.headers["x-trace-id"] = trace_id
        return response

    app.include_router(system.router)
    app.include_router(search.router)
    app.include_router(books.router)
    app.include_router(sources.router)
    app.include_router(tasks.router)
    app.include_router(settings_router.router)
    app.include_router(ws.router)

    return app


# 刻意**不**提供模块级 ``app = create_app()``：
# 那会在 import 时就创建 ~/.inkflow 目录、打开数据库、生成 token，
# 让测试与 CLI 都被副作用污染。
#
# 用 uvicorn 直接跑请加 --factory：
#     uvicorn --factory inkflow_api.app:create_app
# 常规启动走 ``inkflow-server``（见 main.py）。
