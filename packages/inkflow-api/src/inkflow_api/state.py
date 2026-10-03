"""应用状态：把所有长生命周期对象装配在一起。

放在 ``app.state`` 上，路由通过依赖注入取用 —— 全局单例会破坏测试隔离。
"""

from __future__ import annotations

import platform
import sys
from dataclasses import dataclass, field
from time import monotonic

from inkflow_js_runtime import JsRuntime

from inkflow_api.auth import generate_token
from inkflow_api.services import DownloadTaskManager, LibraryService, SqliteHttpCache
from inkflow_core.browser import BrowserProvider, BrowserRegistry
from inkflow_core.config import Settings, get_settings
from inkflow_core.models import BookSource
from inkflow_core.paths import InkFlowPaths, get_paths
from inkflow_core.storage import Database
from inkflow_export import available_formats
from inkflow_source import SearchAggregator, SourceLoader, SourceRegistry
from inkflow_source.http import HttpCache, HttpClient
from inkflow_source.loader import default_loader
from inkflow_source.registration import register_native
from inkflow_source.registry import HttpFactory, default_registry

__all__ = ["AppState", "build_state"]


@dataclass
class AppState:
    """进程级应用状态。"""

    settings: Settings
    paths: InkFlowPaths
    db: Database
    cache: SqliteHttpCache | None
    js: JsRuntime | None
    browser: BrowserProvider | None
    registry: SourceRegistry
    loader: SourceLoader
    aggregator: SearchAggregator
    library: LibraryService
    tasks: DownloadTaskManager
    session_token: str
    started_at: float = field(default_factory=monotonic)

    @property
    def uptime_seconds(self) -> float:
        return monotonic() - self.started_at

    def cache_info(self) -> dict[str, object]:
        """HTTP 缓存概况。未启用时返回零值，字段形状保持一致。"""
        if self.cache is None:
            return {
                "enabled": False,
                "entries": 0,
                "size_bytes": 0,
                "expired_entries": 0,
                "max_size_bytes": None,
            }
        return {"enabled": True, **self.cache.stats()}

    def system_info(self) -> dict[str, object]:
        """运行概况，供 ``/api/v1/system/info`` 使用。"""
        from inkflow_core import __version__

        sources = self.library.list_sources()
        tasks = self.library.list_tasks(limit=1000)
        return {
            "version": __version__,
            "data_dir": str(self.paths.home),
            "uptime_seconds": round(self.uptime_seconds, 2),
            "source_count": len(sources),
            "enabled_source_count": sum(1 for s in sources if s.enabled),
            "book_count": self.library.count_books(),
            "task_count": len(tasks),
            "active_task_count": sum(1 for t in tasks if t.status.is_active),
            "export_formats": available_formats(),
            "source_formats": [str(f) for f in self.loader.supported_formats()],
            "python_version": sys.version.split()[0],
            "platform": platform.platform(),
            "cache": self.cache_info(),
        }

    async def shutdown(self) -> None:
        """优雅关闭：先停任务，再关连接与 sidecar，最后释放数据库。"""
        await self.tasks.shutdown()
        await self.registry.aclose_all()
        if self.js is not None:
            await self.js.close()
        if self.browser is not None:
            await self.browser.close()
        self.db.dispose()


def build_state(
    settings: Settings | None = None,
    *,
    paths: InkFlowPaths | None = None,
    database_url: str | None = None,
    registry: SourceRegistry | None = None,
    loader: SourceLoader | None = None,
    session_token: str | None = None,
) -> AppState:
    """装配应用状态。

    全部依赖都可注入 —— 测试时用临时目录 + 内存数据库即可，
    不需要碰真实的 ``~/.inkflow``。

    Args:
        settings: 配置；省略时读取默认配置。
        paths: 数据目录；省略时用默认值。
        database_url: 数据库连接串；省略时用 ``~/.inkflow/database/inkflow.db``。
        registry: 书源注册表；省略时用进程级默认实例。
        loader: 书源加载器；省略时用进程级默认实例。
        session_token: 会话令牌；省略时随机生成。
    """
    resolved_settings = settings or get_settings()
    resolved_paths = (paths or get_paths()).ensure()
    db = Database(database_url, paths=resolved_paths)
    db.create_all()

    resolved_registry = registry if registry is not None else default_registry
    resolved_loader = loader if loader is not None else default_loader

    # 注册内置书源类型（Legado 兼容层在此接入，Source 层本身不认识它）
    js = _build_js_runtime(resolved_settings)
    browser = _build_browser(resolved_settings)
    _register_source_types(resolved_registry, resolved_loader, js, browser)
    # 让全局请求配置（超时、并发上限、内网访问开关）作用到每个书源
    cache = _build_cache(resolved_settings, db)
    http_factory = _make_http_factory(resolved_settings, cache)
    resolved_registry.set_http_factory(http_factory)

    library = LibraryService(db)
    tasks = DownloadTaskManager(
        registry=resolved_registry,
        library=library,
        settings=resolved_settings,
        paths=resolved_paths,
        # 封面与正文插图走同一套 HTTP 约束，不另起一套配置
        http_factory=http_factory,
    )

    return AppState(
        settings=resolved_settings,
        paths=resolved_paths,
        db=db,
        cache=cache,
        js=js,
        browser=browser,
        registry=resolved_registry,
        loader=resolved_loader,
        aggregator=SearchAggregator(
            resolved_registry, timeout=resolved_settings.source.timeout * 1.5
        ),
        library=library,
        tasks=tasks,
        session_token=session_token or generate_token(),
    )


def _build_cache(settings: Settings, db: Database) -> SqliteHttpCache | None:
    """按配置构造 HTTP 缓存。

    TTL 为 0 等同于不缓存 —— 写进去立刻过期，只会白白占空间，
    不如直接不建这个对象。
    """
    config = settings.cache
    if not config.enabled or config.http_ttl <= 0:
        return None
    return SqliteHttpCache(
        db,
        max_size_bytes=config.max_size_bytes,
        default_ttl=config.http_ttl,
    )


def _make_http_factory(settings: Settings, cache: HttpCache | None) -> HttpFactory:
    """构造 HTTP 客户端工厂。

    书源自己不带全局约束，只有在这里把 ``source`` 段配置注入进去，
    ``allow_private_network`` 这类安全开关才会真正生效。
    """

    def factory(source: BookSource) -> HttpClient:
        return HttpClient.from_source(
            source,
            allow_private_network=settings.source.allow_private_network,
            global_concurrency=settings.source.global_concurrency,
            domain_concurrency=settings.source.domain_concurrency,
            cache=cache,
        )

    return factory


def _register_source_types(
    registry: SourceRegistry,
    loader: SourceLoader,
    js: JsRuntime | None,
    browser: BrowserProvider | None,
) -> None:
    """注册内置书源类型。

    每种类型由自己的包负责注册（原生在 ``inkflow-source``，
    Legado 在 ``inkflow-legado``），Source Engine 本身不认识任何具体类型。

    Legado 兼容层是**可选依赖**：即使它缺失，原生书源仍可正常工作，
    只是导入 Legado 书源时会给出明确错误。
    """
    register_native(registry, loader)

    try:
        from inkflow_legado import register_legado
    except ImportError:  # pragma: no cover - 仅在精简部署时发生
        return

    register_legado(registry, loader, js, browser)


def _build_browser(settings: Settings) -> BrowserProvider | None:
    """按配置构造浏览器引擎。

    未启用时返回 ``None`` —— 此时带 ``webView`` 的规则会抛「未启用」，
    而不是退回普通请求拿到没渲染过的页面。

    **一个实例服务所有书源**：一个浏览器实例几百 MB，按书源起不现实。

    引擎由外层注册（ADR-024）：core 不认识 Playwright，这里显式挂上去。
    """
    if not settings.browser.enabled:
        return None

    from inkflow_browser_playwright import register_playwright

    registry = BrowserRegistry()
    register_playwright(registry)
    return registry.create(settings.browser)


def _build_js_runtime(settings: Settings) -> JsRuntime | None:
    """按配置构造 JS 运行时。

    未启用时返回 ``None`` —— 此时 ``@js:`` 规则会抛「未启用」而不是
    静默返回空。**一个实例服务所有书源**：每个书源起一个 Node 进程太浪费。
    """
    if not settings.js.enabled:
        return None
    return JsRuntime(settings.js)
