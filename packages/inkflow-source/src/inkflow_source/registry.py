"""书源注册表。

持有「书源定义 → 适配器实例」的映射，并提供按来源类型创建适配器的工厂机制。

工厂机制是**兼容层隔离**的关键：``inkflow-source`` 不需要 import
``inkflow-legado``；反过来由 legado 包在启动时把自己的工厂注册进来。
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable, Iterator
from typing import TYPE_CHECKING

from inkflow_core.errors import ErrorCode, NotFoundError, SourceError
from inkflow_core.models import BookSource, SourceType

if TYPE_CHECKING:  # pragma: no cover
    from inkflow_source.adapter import SourceAdapter
    from inkflow_source.http import HttpClient

__all__ = ["SourceFactory", "HttpFactory", "SourceRegistry", "default_registry"]

#: 适配器工厂：``(书源定义, 已配置的 HTTP 客户端) -> 适配器``
SourceFactory = Callable[[BookSource, "HttpClient | None"], "SourceAdapter"]

#: HTTP 客户端工厂：由上层注入，用来把全局配置（超时、SSRF 开关等）
#: 传给每个书源，而不必让适配器自己去读配置。
HttpFactory = Callable[[BookSource], "HttpClient"]


class SourceRegistry:
    """书源适配器注册表。

    Args:
        http_factory: 可选的 HTTP 客户端工厂。省略时适配器会按书源自身配置
            惰性创建客户端（此时全局设置如 ``source.allow_private_network``
            不会生效）。
    """

    def __init__(self, http_factory: HttpFactory | None = None) -> None:
        self._adapters: dict[str, SourceAdapter] = {}
        self._sources: dict[str, BookSource] = {}
        self._factories: dict[SourceType, SourceFactory] = {}
        self._http_factory = http_factory

    def set_http_factory(self, factory: HttpFactory | None) -> None:
        """替换 HTTP 客户端工厂。

        应用启动时调用；已经创建的适配器不受影响。
        """
        self._http_factory = factory

    # -- 工厂 --------------------------------------------------------------

    def register_factory(
        self, source_type: SourceType, factory: SourceFactory, *, replace: bool = False
    ) -> None:
        """注册某类书源的适配器工厂。

        Raises:
            SourceError: 该类型已有工厂且未指定 ``replace``。
        """
        if source_type in self._factories and not replace:
            raise SourceError(
                f"书源类型 {source_type} 的工厂已注册",
                code=ErrorCode.SOURCE_INVALID,
                details={"source_type": str(source_type)},
            )
        self._factories[source_type] = factory

    def has_factory(self, source_type: SourceType) -> bool:
        return source_type in self._factories

    # -- 适配器 ------------------------------------------------------------

    def add(self, source: BookSource, adapter: SourceAdapter, *, replace: bool = False) -> None:
        """直接登记一个适配器实例。"""
        if source.id in self._adapters and not replace:
            raise SourceError(
                f"书源 {source.id} 已存在",
                code=ErrorCode.SOURCE_INVALID,
                details={"source_id": source.id},
            )
        self._sources[source.id] = source
        self._adapters[source.id] = adapter

    def create(self, source: BookSource, *, replace: bool = False) -> SourceAdapter:
        """用已注册的工厂创建并登记适配器。

        若配置了 ``http_factory``，客户端由它统一创建 —— 这样全局设置
        （超时、并发上限、内网访问开关）才能真正作用到每个书源。
        """
        factory = self._factories.get(source.source_type)
        if factory is None:
            raise SourceError(
                f"没有可用于 {source.source_type} 类型书源的适配器工厂",
                code=ErrorCode.SOURCE_INVALID,
                details={"source_id": source.id, "source_type": str(source.source_type)},
            )
        http = self._http_factory(source) if self._http_factory is not None else None
        adapter = factory(source, http)
        self.add(source, adapter, replace=replace)
        return adapter

    def remove(self, source_id: str) -> None:
        """移除书源。不存在时静默返回。"""
        self._adapters.pop(source_id, None)
        self._sources.pop(source_id, None)

    # -- 查询 --------------------------------------------------------------

    def get(self, source_id: str) -> SourceAdapter:
        """按 ID 取适配器。

        Raises:
            NotFoundError: 书源不存在。
        """
        try:
            return self._adapters[source_id]
        except KeyError:
            raise NotFoundError(
                f"书源不存在: {source_id}",
                code=ErrorCode.SOURCE_NOT_FOUND,
                details={"source_id": source_id},
            ) from None

    def source(self, source_id: str) -> BookSource:
        """按 ID 取书源定义。"""
        try:
            return self._sources[source_id]
        except KeyError:
            raise NotFoundError(
                f"书源不存在: {source_id}",
                code=ErrorCode.SOURCE_NOT_FOUND,
                details={"source_id": source_id},
            ) from None

    def all(self) -> list[SourceAdapter]:
        """全部适配器。"""
        return list(self._adapters.values())

    def enabled(self) -> list[SourceAdapter]:
        """已启用的适配器。"""
        return [a for a in self._adapters.values() if a.source.enabled]

    def searchable(self) -> list[SourceAdapter]:
        """可用于搜索的适配器，按优先级降序。"""
        items = [a for a in self._adapters.values() if a.source.enabled and a.source.enabled_search]
        return sorted(items, key=lambda a: a.source.priority, reverse=True)

    def resolve(self, source_ids: list[str] | None = None) -> list[SourceAdapter]:
        """把可选的 ID 列表解析成适配器列表；``None`` 表示全部可搜索书源。"""
        if not source_ids:
            return self.searchable()
        return [self.get(sid) for sid in source_ids]

    def __len__(self) -> int:
        return len(self._adapters)

    def __iter__(self) -> Iterator[SourceAdapter]:
        return iter(self._adapters.values())

    def __contains__(self, source_id: object) -> bool:
        return source_id in self._adapters

    # -- 生命周期 ----------------------------------------------------------

    async def aclose_all(self) -> None:
        """关闭所有适配器。单个失败不影响其余。"""
        for adapter in list(self._adapters.values()):
            # 关闭阶段的异常不应中断整体清理
            with contextlib.suppress(Exception):
                await adapter.aclose()
        self._adapters.clear()
        self._sources.clear()


#: 进程级默认注册表。多实例场景（测试）请自行 new 一个。
default_registry = SourceRegistry()
