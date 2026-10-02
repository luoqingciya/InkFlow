"""内置书源类型的注册。

与 ``inkflow_legado.register_legado`` 对称：每种书源类型由**自己的包**
负责把自己的工厂注册进 Source Engine，``inkflow-source`` 不认识任何具体类型。
"""

from __future__ import annotations

from inkflow_core.models import BookSource, SourceFormat, SourceType
from inkflow_source.http import HttpClient
from inkflow_source.loader import SourceLoader, build_native_source, default_loader
from inkflow_source.native.adapter import NativeSourceAdapter
from inkflow_source.native.schema import NativeSourceSpec
from inkflow_source.registry import SourceRegistry, default_registry

__all__ = ["register_native", "native_factory"]


def native_factory(source: BookSource, http: HttpClient | None = None) -> NativeSourceAdapter:
    """构造原生书源适配器。

    Raises:
        SourceError: 书源内容无法解析成原生规格。
    """
    spec = NativeSourceSpec.from_raw(source.raw)
    return NativeSourceAdapter(source, spec, http)


def register_native(
    registry: SourceRegistry | None = None,
    loader: SourceLoader | None = None,
) -> None:
    """把原生书源的工厂与解析器注册进去。幂等。"""
    target_registry = registry if registry is not None else default_registry
    target_loader = loader if loader is not None else default_loader

    target_registry.register_factory(SourceType.NATIVE, native_factory, replace=True)
    target_loader.register_format_parser(
        SourceFormat.NATIVE_YAML, build_native_source, replace=True
    )
