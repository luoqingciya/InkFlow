"""Markdown 导出器。

适合做二次加工：转成静态站点、喂给其他工具、或直接丢进笔记软件。
"""

from __future__ import annotations

from pathlib import Path

from inkflow_export.base import ExportRequest

__all__ = ["MarkdownExporter"]


class MarkdownExporter:
    """把整本书导出为 Markdown。

    Args:
        heading_level: 章节标题层级，默认 ``##``。
        with_front_matter: 是否写入 YAML front matter。
        with_toc: 是否在开头生成目录。
    """

    format = "markdown"
    extension = ".md"

    def __init__(
        self,
        *,
        heading_level: int = 2,
        with_front_matter: bool = True,
        with_toc: bool = True,
    ) -> None:
        self.heading_level = max(1, min(6, heading_level))
        self.with_front_matter = with_front_matter
        self.with_toc = with_toc

    def export(self, request: ExportRequest) -> Path:
        """写出 Markdown 文件。"""
        output = Path(request.output_path)
        output.parent.mkdir(parents=True, exist_ok=True)

        book = request.book
        parts: list[str] = []

        if self.with_front_matter:
            parts.append("---")
            parts.append(f"title: {_yaml_scalar(book.name)}")
            if book.author:
                parts.append(f"author: {_yaml_scalar(book.author)}")
            if request.source_name:
                parts.append(f"source: {_yaml_scalar(request.source_name)}")
            parts.append(f"chapters: {len(request.chapters)}")
            parts.append("---")
            parts.append("")

        parts.append(f"# {book.name}")
        parts.append("")
        if book.intro:
            parts.append(f"> {book.intro.strip()}")
            parts.append("")

        if self.with_toc:
            parts.append("## 目录")
            parts.append("")
            for item in request.chapters:
                anchor = _anchor(item.title)
                parts.append(f"- [{item.title}](#{anchor})")
            parts.append("")

        heading = "#" * self.heading_level
        for item in request.chapters:
            parts.append(f"{heading} {item.title}")
            parts.append("")
            for line in item.text.split("\n"):
                if line.strip():
                    parts.append(line.strip())
                    parts.append("")

        output.write_text("\n".join(parts).rstrip() + "\n", encoding="utf-8")
        return output


def _yaml_scalar(value: str) -> str:
    """把字符串安全地写进 YAML 标量。"""
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _anchor(title: str) -> str:
    """生成与常见 Markdown 渲染器一致的标题锚点。"""
    lowered = title.strip().lower()
    return "".join(
        ch if ch.isalnum() or ch in "-_" else ("-" if ch.isspace() else "") for ch in lowered
    )
