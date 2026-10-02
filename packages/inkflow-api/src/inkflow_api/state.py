"""应用状态：把所有长生命周期对象装配在一起。

放在 ``app.state`` 上，路由通过依赖注入取用 —— 全局单例会破坏测试隔离。
"""

from __future__ import annotations

import platform
import sys
from dataclasses import dataclass, field
from time import monotonic

from inkflow_api.auth import generate_token
from inkflow_api.services import DownloadTaskManager, LibraryService
from inkflow_core.config import Settings, get_settings
from inkflow_core.models import BookSource
from inkflow_core.paths import InkFlowPaths, get_paths
from inkflow_core.storage import Database
from inkflow_export import available_formats
from inkflow_source import SearchAggregator, SourceLoader, SourceRegistry
from inkflow_source.http import HttpClient
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
        }

    async def shutdown(self) -> None:
        """优雅关闭：先停任务，再关连接，最后释放数据库。"""
        await self.tasks.shutdown()
        await self.registry.aclose_all()
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
    _register_source_types(resolved_registry, resolved_loader)
    # 让全局请求配置（超时、并发上限、内网访问开关）作用到每个书源
    resolved_registry.set_http_factory(_make_http_factory(resolved_settings))

    library = LibraryService(db)
    tasks = DownloadTaskManager(
        registry=resolved_registry,
        library=library,
        settings=resolved_settings,
        paths=resolved_paths,
    )

    return AppState(
        settings=resolved_settings,
        paths=resolved_paths,
        db=db,
        registry=resolved_registry,
        loader=resolved_loader,
        aggregator=SearchAggregator(
            resolved_registry, timeout=resolved_settings.source.timeout * 1.5
        ),
        library=library,
        tasks=tasks,
        session_token=session_token or generate_token(),
    )


def _make_http_factory(settings: Settings) -> HttpFactory:
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
        )

    return factory


def _register_source_types(registry: SourceRegistry, loader: SourceLoader) -> None:
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
    register_legado(registry, loader)
