"""书源加载（规划书 §41）。

把外部输入（YAML / JSON 文件、剪贴板文本、URL 内容）转成统一的 ``BookSource``。

**格式解析是可插拔的**：``inkflow-source`` 只认识原生 YAML；
Legado JSON / JS 由 ``inkflow-legado`` 在启动时通过 ``register_format_parser``
注册进来。这样 source 包永远不需要 import legado 包。
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml

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

__all__ = [
    "FormatParser",
    "SourceLoader",
    "build_native_source",
    "detect_format",
]

#: 格式解析器：``(原始数据, 来源信息) -> BookSource``
FormatParser = Callable[[dict[str, Any], str | None], BookSource]


def detect_format(data: dict[str, Any], *, filename: str | None = None) -> SourceFormat:
    """猜测书源格式。

    判定顺序：先看 Legado 特征字段（最不容易误判），再看原生字段，
    最后才退回文件扩展名。
    """
    if "bookSourceUrl" in data or "bookSourceName" in data:
        if any(key.startswith("rule") for key in data) or "searchUrl" in data:
            return SourceFormat.LEGADO_JSON
        return SourceFormat.LEGADO_JSON
    if {"name", "url"} <= data.keys():
        return SourceFormat.NATIVE_YAML
    if filename:
        suffix = Path(filename).suffix.lower()
        if suffix in {".yaml", ".yml"}:
            return SourceFormat.NATIVE_YAML
        if suffix == ".json":
            return SourceFormat.LEGADO_JSON
    raise SourceError(
        "无法识别书源格式：缺少 bookSourceUrl（Legado）或 name/url（原生）字段",
        code=ErrorCode.SOURCE_INVALID,
        details={"keys": sorted(data.keys())[:20]},
    )


def build_native_source(
    data: dict[str, Any],
    origin: str | None = None,
    *,
    source_id: str | None = None,
) -> BookSource:
    """从原生 YAML 数据构建 ``BookSource``。

    ``origin`` 必须是位置参数 —— 它由 ``SourceLoader`` 按 ``(data, origin)``
    的位置约定调用，与 ``FormatParser`` 的签名保持一致。
    """
    from inkflow_source.native.schema import NativeSourceSpec

    try:
        spec = NativeSourceSpec.from_raw(data)
    except Exception as exc:
        raise SourceError(
            f"原生书源校验失败：{exc}",
            code=ErrorCode.SOURCE_INVALID,
            details={"origin": origin},
        ) from exc

    return BookSource(
        # 用地址派生稳定 ID，重复导入同一书源才是幂等的
        id=source_id or stable_id("src", spec.url),
        name=spec.name,
        url=spec.url,
        source_type=SourceType.NATIVE,
        source_format=SourceFormat.NATIVE_YAML,
        compatibility_level=CompatibilityLevel.NATIVE,
        enabled_search=spec.search is not None,
        request=RequestConfig(
            concurrency=spec.concurrency,
            requests_per_second=spec.requests_per_second,
            timeout=spec.timeout,
            retry=spec.retry,
            headers=dict(spec.headers),
            user_agent=spec.user_agent,
        ),
        meta=SourceMeta(
            author=spec.author,
            version=spec.version,
            license=spec.license,
            description=spec.description,
        ),
        raw=data,
    )


class SourceLoader:
    """按格式分派的书源加载器。"""

    def __init__(self) -> None:
        self._parsers: dict[SourceFormat, FormatParser] = {
            SourceFormat.NATIVE_YAML: build_native_source,
        }

    def register_format_parser(
        self, fmt: SourceFormat, parser: FormatParser, *, replace: bool = False
    ) -> None:
        """注册某格式的解析器。

        Raises:
            SourceError: 该格式已有解析器且未指定 ``replace``。
        """
        if fmt in self._parsers and not replace:
            raise SourceError(
                f"格式 {fmt} 的解析器已注册",
                code=ErrorCode.SOURCE_INVALID,
                details={"format": str(fmt)},
            )
        self._parsers[fmt] = parser

    def supported_formats(self) -> list[SourceFormat]:
        return sorted(self._parsers, key=str)

    # -- 入口 --------------------------------------------------------------

    def load_dict(
        self,
        data: dict[str, Any],
        *,
        fmt: SourceFormat | None = None,
        origin: str | None = None,
        source_id: str | None = None,
    ) -> BookSource:
        """从已解析的字典加载书源。"""
        resolved = fmt or detect_format(data, filename=origin)
        parser = self._parsers.get(resolved)
        if parser is None:
            raise SourceError(
                f"没有可用于 {resolved} 格式的解析器",
                code=ErrorCode.SOURCE_INVALID,
                details={"format": str(resolved), "supported": [str(f) for f in self._parsers]},
            )
        source = parser(data, origin)
        if source_id:
            source.id = source_id
        return source

    def load_text(
        self,
        text: str,
        *,
        fmt: SourceFormat | None = None,
        origin: str | None = None,
    ) -> BookSource:
        """从 YAML / JSON 文本加载。"""
        stripped = text.lstrip()
        try:
            if stripped.startswith("{") or fmt is SourceFormat.LEGADO_JSON:
                data = json.loads(text)
            else:
                data = yaml.safe_load(text)
        except (yaml.YAMLError, json.JSONDecodeError) as exc:
            raise SourceError(
                f"书源内容无法解析：{exc}",
                code=ErrorCode.SOURCE_INVALID,
                details={"origin": origin},
            ) from exc

        if not isinstance(data, dict):
            raise SourceError(
                "书源内容必须是对象（顶层为 mapping）",
                code=ErrorCode.SOURCE_INVALID,
                details={"origin": origin, "type": type(data).__name__},
            )
        return self.load_dict(data, fmt=fmt, origin=origin)

    def load_file(self, path: str | Path) -> BookSource:
        """从文件加载。"""
        file_path = Path(path)
        if not file_path.is_file():
            raise SourceError(
                f"书源文件不存在：{file_path}",
                code=ErrorCode.SOURCE_INVALID,
                details={"path": str(file_path)},
            )
        return self.load_text(
            file_path.read_text(encoding="utf-8"),
            origin=str(file_path),
        )


#: 进程级默认加载器
default_loader = SourceLoader()
