"""导出器契约（规划书 §23.3）。

新增一种格式 = 新增一个 ``Exporter`` 实现并注册，不修改既有代码。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable

from inkflow_core.models import Book, Chapter, ChapterContent

__all__ = [
    "ExportChapter",
    "ExportRequest",
    "Exporter",
    "available_formats",
    "get_exporter",
    "register_exporter",
    "sanitize_filename",
]

#: Windows 与 POSIX 通用的非法文件名字符
_ILLEGAL_FILENAME_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED_NAMES = frozenset(
    {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        "COM1",
        "COM2",
        "COM3",
        "COM4",
        "COM5",
        "COM6",
        "COM7",
        "COM8",
        "COM9",
        "LPT1",
        "LPT2",
        "LPT3",
        "LPT4",
        "LPT5",
        "LPT6",
        "LPT7",
        "LPT8",
        "LPT9",
    }
)


def sanitize_filename(name: str, *, fallback: str = "untitled", max_length: int = 120) -> str:
    """把书名转成安全的文件名。

    处理 Windows 保留名（``CON`` / ``NUL`` 等）与非法字符，
    并限制长度 —— 超长书名会让导出在部分文件系统上直接失败。
    """
    cleaned = _ILLEGAL_FILENAME_RE.sub("_", name).strip().strip(".")
    cleaned = re.sub(r"\s+", " ", cleaned)
    if not cleaned:
        return fallback
    if cleaned.upper() in _RESERVED_NAMES:
        cleaned = f"_{cleaned}"
    if len(cleaned) > max_length:
        cleaned = cleaned[:max_length].rstrip()
    return cleaned or fallback


@dataclass(slots=True)
class ExportChapter:
    """导出用的一章：元数据 + 正文。"""

    chapter: Chapter
    content: ChapterContent | None = None

    @property
    def index(self) -> int:
        return self.chapter.index

    @property
    def title(self) -> str:
        return self.chapter.name

    @property
    def text(self) -> str:
        if self.content is None:
            return ""
        return self.content.clean_content or self.content.raw_content


@dataclass(slots=True)
class ExportRequest:
    """一次导出请求。

    Attributes:
        book: 书籍元数据。
        chapters: 章节列表，**必须已按 index 升序**。
        output_path: 目标文件路径（含扩展名）。
        source_name: 书源名称，写入 EPUB 的贡献者信息。
        cover_bytes: 封面图片数据，``None`` 表示无封面。
        cover_media_type: 封面 MIME 类型。
        extra: 格式特有的附加选项。
    """

    book: Book
    chapters: list[ExportChapter]
    output_path: Path
    source_name: str = ""
    cover_bytes: bytes | None = None
    cover_media_type: str = "image/jpeg"
    extra: dict[str, object] = field(default_factory=dict)

    @property
    def filename_stem(self) -> str:
        return sanitize_filename(self.book.name)


@runtime_checkable
class Exporter(Protocol):
    """导出器协议。"""

    #: 格式标识，与 ``ExportFormat`` 对应
    format: str
    #: 输出文件扩展名（含点）
    extension: str

    def export(self, request: ExportRequest) -> Path:
        """执行导出，返回实际写入的文件路径。"""
        ...


_REGISTRY: dict[str, Exporter] = {}


def register_exporter(exporter: Exporter, *, replace: bool = False) -> None:
    """注册导出器。

    Raises:
        ValueError: 格式已注册且未指定 ``replace``。
    """
    fmt = exporter.format.lower()
    if fmt in _REGISTRY and not replace:
        raise ValueError(f"导出格式 {fmt} 已注册")
    _REGISTRY[fmt] = exporter


def get_exporter(fmt: str) -> Exporter:
    """按格式取导出器。

    Raises:
        ValueError: 格式未注册。
    """
    key = fmt.lower()
    if key not in _REGISTRY:
        raise ValueError(f"不支持的导出格式: {fmt!r}，可选 {sorted(_REGISTRY)}")
    return _REGISTRY[key]


def available_formats() -> list[str]:
    """已注册的导出格式。"""
    return sorted(_REGISTRY)
