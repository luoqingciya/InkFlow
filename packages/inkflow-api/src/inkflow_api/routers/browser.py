"""浏览器运行时路由：状态查询与按需下载。

浏览器默认不随分发（ADR-024）—— 首次启用时用户要能一键装上，
而不是被指去命令行。

引擎包是**可选**的（冻结构建里可能没有），所以这里的导入都放在函数里 ——
导入失败不该让整个 API 起不来。
"""

from __future__ import annotations

from fastapi import APIRouter
from starlette.concurrency import run_in_threadpool

from inkflow_api.deps import StateDep
from inkflow_api.schemas import BrowserInstallResponse, BrowserStatusResponse
from inkflow_core.browser import BrowserUnavailableError
from inkflow_core.errors import ErrorCode, InkFlowError

__all__ = ["router"]

router = APIRouter(tags=["browser"])

_ENGINE_MISSING = (
    "这个构建没有带浏览器引擎，需要浏览器渲染的书源不可用。\n"
    "用 pip / uv 安装的环境才支持：\n"
    '  pip install "inkflow-browser-playwright[playwright]"'
)


@router.get(
    "/api/v1/browser/status",
    response_model=BrowserStatusResponse,
    summary="浏览器运行时状态",
)
async def browser_status(state: StateDep) -> BrowserStatusResponse:
    """是否启用、浏览器装了没。

    桌面端用它决定要不要弹「下载浏览器」的引导。
    """
    config = state.settings.browser

    try:
        from inkflow_browser_playwright import browser_installed, browsers_dir
    except ImportError:  # pragma: no cover - 精简部署 / 冻结构建没带引擎
        return BrowserStatusResponse(
            enabled=config.enabled,
            engine=config.engine,
            install_dir="",
            installed=False,
            engine_available=False,
            message=_ENGINE_MISSING,
        )

    installed = browser_installed(config)
    return BrowserStatusResponse(
        enabled=config.enabled,
        engine=config.engine,
        install_dir=str(browsers_dir(config)),
        installed=installed,
        engine_available=True,
        message=None if installed else "浏览器未安装，需要先下载（约 270MB）。",
    )


@router.post(
    "/api/v1/browser/install",
    response_model=BrowserInstallResponse,
    summary="下载浏览器",
)
async def browser_install(state: StateDep) -> BrowserInstallResponse:
    """下载浏览器到数据目录（约 270MB）。

    **这是一个会阻塞几分钟的请求** —— 一次性操作，调用方自己把超时放宽。
    下载在线程里跑，不占事件循环。
    """
    try:
        from inkflow_browser_playwright import browsers_dir, install_browser
    except ImportError as exc:  # pragma: no cover - 精简部署 / 冻结构建没带引擎
        raise InkFlowError(
            _ENGINE_MISSING,
            code=ErrorCode.BROWSER_UNAVAILABLE,
            status_code=503,
            details={"engine": state.settings.browser.engine},
        ) from exc

    config = state.settings.browser
    try:
        directory = await run_in_threadpool(install_browser, config)
    except BrowserUnavailableError as exc:
        raise InkFlowError(
            str(exc),
            code=ErrorCode.BROWSER_INSTALL_FAILED,
            status_code=503,
            details={"engine": config.engine, "install_dir": str(browsers_dir(config))},
        ) from exc

    return BrowserInstallResponse(
        installed=True,
        install_dir=str(directory),
        message=f"浏览器已装到 {directory}",
    )
