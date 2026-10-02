"""TXT 导出器。

最简单的格式，也是兼容性最好的 —— 任何设备都能读。
"""

from __future__ import annotations

from pathlib import Path

from inkflow_export.base import ExportRequest

__all__ = ["TxtExporter"]


class TxtExporter:
    """把整本书拼成单个纯文本文件。

    Args:
        chapter_separator: 章节之间的分隔行；``None`` 表示只用空行。
        with_header: 是否在开头写入书名 / 作者信息块。
        line_ending: 换行符，默认 ``\\n``。
    """

    format = "txt"
    extension = ".txt"

    def __init__(
        self,
        *,
        chapter_separator: str | None = "\n\n",
        with_header: bool = True,
        line_ending: str = "\n",
    ) -> None:
        self.chapter_separator = chapter_separator
        self.with_header = with_header
        self.line_ending = line_ending

    def export(self, request: ExportRequest) -> Path:
        """写出 TXT 文件。"""
        output = Path(request.output_path)
        output.parent.mkdir(parents=True, exist_ok=True)

        blocks: list[str] = []
        if self.with_header:
            blocks.append(self._header(request))

        for item in request.chapters:
            body = item.text.strip()
            blocks.append(f"{item.title}{self.line_ending}{self.line_ending}{body}")

        separator = self.chapter_separator if self.chapter_separator is not None else "\n"
        content = separator.join(blocks).strip() + self.line_ending

        # 用 utf-8-sig：Windows 记事本等工具靠 BOM 才能正确识别中文编码
        output.write_text(content, encoding="utf-8-sig", newline="")
        return output

    @staticmethod
    def _header(request: ExportRequest) -> str:
        """书籍信息块。"""
        book = request.book
        lines = [book.name]
        if book.author:
            lines.append(f"作者：{book.author}")
        if request.source_name:
            lines.append(f"来源：{request.source_name}")
        lines.append(f"章节数：{len(request.chapters)}")
        lines.append("")
        return "\n".join(lines)
