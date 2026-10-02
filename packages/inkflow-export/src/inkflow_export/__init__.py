"""inkflow-export —— 导出器。

新增格式只需实现 ``Exporter`` 协议并调用 ``register_exporter``。
本包只依赖 ``inkflow-core``（消费 Book / Chapter / ChapterContent），
不依赖网络层，因此可以脱离 API 单独使用。
"""

from inkflow_export.base import (
    ExportChapter,
    Exporter,
    ExportRequest,
    available_formats,
    get_exporter,
    register_exporter,
    sanitize_filename,
)
from inkflow_export.epub import EpubExporter
from inkflow_export.markdown import MarkdownExporter
from inkflow_export.txt import TxtExporter

__version__ = "0.1.0"

__all__ = [
    "__version__",
    # base
    "Exporter",
    "ExportRequest",
    "ExportChapter",
    "register_exporter",
    "get_exporter",
    "available_formats",
    "sanitize_filename",
    # exporters
    "TxtExporter",
    "EpubExporter",
    "MarkdownExporter",
]


def _register_defaults() -> None:
    """注册内置导出器。

    HTML 导出器尚未实现（规划书 §23.3 中的 ``HtmlExporter``）——
    需要时会话内补上，接口已就位。
    """
    for exporter in (TxtExporter(), EpubExporter(), MarkdownExporter()):
        register_exporter(exporter, replace=True)


_register_defaults()
