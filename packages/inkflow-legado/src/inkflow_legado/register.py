"""把 Legado 兼容层接入 Source Engine。

**这是「外层隔离」的落地点。** ``inkflow-source`` 不知道 Legado 的存在；
由本模块在应用启动时把工厂与格式解析器注册进去。

依赖方向因此保持单向：

    inkflow-core ← inkflow-source ← inkflow-legado

将来升级 Legado 兼容性只需要动这个包，Core / API / CLI / Desktop 都不受影响。
"""

from __future__ import annotations

from typing import Any

from inkflow_core.errors import ErrorCode, SourceError
from inkflow_core.models import (
    BookSource,
    CompatibilityLevel,
    RequestConfig,
    SourceFormat,
    SourceMeta,
    SourceType,
)
from inkflow_core.utils import stable_id
from inkflow_legado.adapter import LegadoSourceAdapter
from inkflow_legado.schema import LegadoBookSource
from inkflow_source.loader import SourceLoader, default_loader
from inkflow_source.registry import SourceRegistry, default_registry

__all__ = ["build_legado_source", "detect_level", "register_legado", "stable_source_id"]


def stable_source_id(url: str) -> str:
    """由书源地址推导稳定 ID（与原生书源共用同一套规则）。"""
    return stable_id("src", url)


def detect_level(definition: LegadoBookSource) -> CompatibilityLevel:
    """判定书源的兼容等级（规划书 §7）。"""
    if definition.needs_browser():
        return CompatibilityLevel.L3
    if definition.uses_js():
        return CompatibilityLevel.L2
    has_rules = any(
        [
            definition.ruleSearch.bookList,
            definition.ruleBookInfo.name,
            definition.ruleToc.chapterList,
            definition.ruleContent.content,
        ]
    )
    return CompatibilityLevel.L1 if has_rules else CompatibilityLevel.L0


def build_legado_source(
    data: dict[str, Any],
    origin: str | None = None,
    *,
    source_id: str | None = None,
) -> BookSource:
    """把 Legado 书源 JSON 转成统一的 ``BookSource``。

    Raises:
        SourceError: 结构校验失败（缺少 bookSourceName / bookSourceUrl）。
    """
    try:
        definition = LegadoBookSource.model_validate(data)
    except Exception as exc:
        raise SourceError(
            f"Legado 书源校验失败：{exc}",
            code=ErrorCode.SOURCE_INVALID,
            details={"origin": origin},
        ) from exc

    level = detect_level(definition)
    concurrency = _parse_concurrent_rate(definition.concurrentRate)

    return BookSource(
        id=source_id or stable_source_id(definition.bookSourceUrl),
        name=definition.bookSourceName,
        url=definition.bookSourceUrl,
        enabled=definition.enabled,
        priority=max(-100, min(100, definition.customOrder)),
        source_type=SourceType.LEGADO,
        source_format=SourceFormat.LEGADO_JSON,
        compatibility_level=level,
        enabled_search=definition.search_enabled,
        enabled_explore=definition.explore_enabled,
        request=RequestConfig(
            concurrency=concurrency,
            headers=definition.headers,
        ),
        meta=SourceMeta(
            author=None,
            version=None,
            homepage=definition.bookSourceUrl,
            description=definition.bookSourceComment or None,
            requires_browser=level is CompatibilityLevel.L3,
        ),
        raw=definition.raw_dict(),
    )


def _parse_concurrent_rate(value: str) -> int:
    """解析 Legado 的 ``concurrentRate`` 扩展字段。

    格式形如 ``"3/1000"``（3 次 / 1000 毫秒），只取并发数。
    解析不出来时返回保守值 3。
    """
    if not value:
        return 3
    head = value.split("/", 1)[0].strip()
    try:
        number = int(head)
    except ValueError:
        return 3
    return max(1, min(32, number))


def register_legado(
    registry: SourceRegistry | None = None,
    loader: SourceLoader | None = None,
) -> None:
    """把 Legado 工厂与格式解析器注册到 Source Engine。

    幂等：重复调用会覆盖既有注册项，不报错。
    """
    target_registry = registry if registry is not None else default_registry
    target_loader = loader if loader is not None else default_loader

    target_registry.register_factory(
        SourceType.LEGADO, LegadoSourceAdapter.from_source, replace=True
    )
    target_loader.register_format_parser(
        SourceFormat.LEGADO_JSON, build_legado_source, replace=True
    )
