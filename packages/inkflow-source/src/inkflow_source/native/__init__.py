"""原生书源（Level 1）：声明式 YAML，无代码执行。"""

from inkflow_source.native.adapter import NativeSourceAdapter
from inkflow_source.native.schema import (
    BookInfoSpec,
    ContentSpec,
    FieldSpec,
    ListSpec,
    NativeSourceSpec,
    RequestSpec,
    SearchSpec,
    TocSpec,
)

__all__ = [
    "BookInfoSpec",
    "ContentSpec",
    "FieldSpec",
    "ListSpec",
    "NativeSourceAdapter",
    "NativeSourceSpec",
    "RequestSpec",
    "SearchSpec",
    "TocSpec",
]
