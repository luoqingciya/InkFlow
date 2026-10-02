"""EPUB 导出器（规划书 §24）。

手写 EPUB 3 结构，不引入额外依赖 —— 生成逻辑不复杂，而少一个依赖就少一份
许可证审查与打包体积。

产物结构::

    book.epub
     ├── mimetype                    （必须首个条目且不压缩）
     ├── META-INF/container.xml
     └── OEBPS/
         ├── content.opf
         ├── nav.xhtml               （EPUB 3 导航）
         ├── toc.ncx                 （EPUB 2 兼容）
         ├── style.css
         ├── cover.xhtml             （有封面时）
         ├── images/cover.jpg
         └── text/chapter-001.xhtml
             text/chapter-002.xhtml
             ...
"""

from __future__ import annotations

import uuid
import zipfile
from datetime import UTC, datetime
from html import escape
from pathlib import Path

from inkflow_export.base import ExportRequest

__all__ = ["DEFAULT_STYLESHEET", "EpubExporter"]

DEFAULT_STYLESHEET = """\
body {
    margin: 1em;
    line-height: 1.6;
    font-family: "Noto Serif CJK SC", "Source Han Serif SC", serif;
}
h1 {
    font-size: 1.3em;
    margin: 0.8em 0 1.2em;
    text-align: center;
    font-weight: normal;
}
p {
    margin: 0;
    text-indent: 2em;
    text-align: justify;
}
"""

#: 封面图扩展名 → MIME 类型
_MEDIA_TYPES = {
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/png": "png",
    "image/gif": "gif",
    "image/webp": "webp",
}


class EpubExporter:
    """生成 EPUB 3 文件（同时带 NCX 以兼容旧阅读器）。

    Args:
        language: 语言标签，写入 ``dc:language``。
        stylesheet: 自定义 CSS；``None`` 时使用内置样式。
        include_cover_page: 是否生成独立的封面页。
        indent_paragraphs: 段落是否首行缩进（由 CSS 控制）。
    """

    format = "epub"
    extension = ".epub"

    def __init__(
        self,
        *,
        language: str = "zh",
        stylesheet: str | None = None,
        include_cover_page: bool = True,
        indent_paragraphs: bool = True,
    ) -> None:
        self.language = language
        self.stylesheet = stylesheet or DEFAULT_STYLESHEET
        self.include_cover_page = include_cover_page
        self.indent_paragraphs = indent_paragraphs

    # -- 对外入口 ----------------------------------------------------------

    def export(self, request: ExportRequest) -> Path:
        """写出 EPUB 文件。"""
        output = Path(request.output_path)
        output.parent.mkdir(parents=True, exist_ok=True)

        book_id = f"urn:uuid:{uuid.uuid5(uuid.NAMESPACE_URL, request.book.id)}"
        modified = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

        cover_name: str | None = None
        cover_media_type: str | None = None
        if request.cover_bytes:
            cover_media_type = request.cover_media_type
            suffix = _MEDIA_TYPES.get(cover_media_type, "jpg")
            cover_name = f"images/cover.{suffix}"

        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as zf:
            self._write_mimetype(zf)
            zf.writestr("META-INF/container.xml", self._container_xml())
            zf.writestr("OEBPS/style.css", self._stylesheet())
            zf.writestr(
                "OEBPS/content.opf",
                self._opf(request, book_id, modified, cover_name, cover_media_type),
            )
            zf.writestr("OEBPS/nav.xhtml", self._nav(request))
            zf.writestr("OEBPS/toc.ncx", self._ncx(request, book_id))

            if cover_name and request.cover_bytes:
                zf.writestr(f"OEBPS/{cover_name}", request.cover_bytes)
                if self.include_cover_page:
                    zf.writestr(
                        "OEBPS/cover.xhtml",
                        self._cover_page(cover_name.removeprefix("images/")),
                    )

            for item in request.chapters:
                zf.writestr(
                    f"OEBPS/text/{self._chapter_filename(item.index)}",
                    self._chapter_xhtml(item.title, item.text),
                )

        return output

    # -- 各部件 ------------------------------------------------------------

    @staticmethod
    def _write_mimetype(zf: zipfile.ZipFile) -> None:
        """写 mimetype 条目。

        EPUB 规范要求它是压缩包里的**第一个**条目且**不压缩** ——
        否则阅读器无法通过魔数识别格式。
        """
        info = zipfile.ZipInfo("mimetype")
        info.compress_type = zipfile.ZIP_STORED
        zf.writestr(info, "application/epub+zip")

    @staticmethod
    def _container_xml() -> str:
        return (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<container version="1.0" '
            'xmlns="urn:oasis:names:tc:opendocument:xmlns:container">\n'
            "  <rootfiles>\n"
            '    <rootfile full-path="OEBPS/content.opf" '
            'media-type="application/oebps-package+xml"/>\n'
            "  </rootfiles>\n"
            "</container>\n"
        )

    def _stylesheet(self) -> str:
        css = self.stylesheet
        if not self.indent_paragraphs:
            css = css.replace("text-indent: 2em;", "text-indent: 0;")
        return css

    @staticmethod
    def _chapter_filename(index: int) -> str:
        return f"chapter-{index + 1:04d}.xhtml"

    def _opf(
        self,
        request: ExportRequest,
        book_id: str,
        modified: str,
        cover_name: str | None,
        cover_media_type: str | None,
    ) -> str:
        """生成 OPF 包文档。"""
        book = request.book
        parts: list[str] = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" '
            'unique-identifier="bookid" xml:lang="' + escape(self.language) + '">',
            '  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">',
            f'    <dc:identifier id="bookid">{escape(book_id)}</dc:identifier>',
            f"    <dc:title>{escape(book.name)}</dc:title>",
            f"    <dc:language>{escape(self.language)}</dc:language>",
        ]
        if book.author:
            parts.append(f"    <dc:creator>{escape(book.author)}</dc:creator>")
        if book.intro:
            parts.append(f"    <dc:description>{escape(book.intro)}</dc:description>")
        if request.source_name:
            parts.append(f"    <dc:contributor>{escape(request.source_name)}</dc:contributor>")
        parts.append(f'    <meta property="dcterms:modified">{modified}</meta>')
        if cover_name:
            parts.append('    <meta name="cover" content="cover-image"/>')
        parts.append("  </metadata>")

        # manifest
        parts.append("  <manifest>")
        parts.append(
            '    <item id="nav" href="nav.xhtml" '
            'media-type="application/xhtml+xml" properties="nav"/>'
        )
        parts.append('    <item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>')
        parts.append('    <item id="css" href="style.css" media-type="text/css"/>')
        if cover_name and cover_media_type:
            parts.append(
                f'    <item id="cover-image" href="{escape(cover_name)}" '
                f'media-type="{escape(cover_media_type)}"/>'
            )
            if self.include_cover_page:
                parts.append(
                    '    <item id="cover" href="cover.xhtml" media-type="application/xhtml+xml"/>'
                )
        for item in request.chapters:
            filename = self._chapter_filename(item.index)
            parts.append(
                f'    <item id="ch{item.index}" href="text/{filename}" '
                'media-type="application/xhtml+xml"/>'
            )
        parts.append("  </manifest>")

        # spine
        parts.append('  <spine toc="ncx">')
        if cover_name and self.include_cover_page:
            parts.append('    <itemref idref="cover"/>')
        for item in request.chapters:
            parts.append(f'    <itemref idref="ch{item.index}"/>')
        parts.append("  </spine>")
        parts.append("</package>")
        return "\n".join(parts) + "\n"

    def _nav(self, request: ExportRequest) -> str:
        """EPUB 3 导航文档。"""
        items = "\n".join(
            f'      <li><a href="text/{self._chapter_filename(item.index)}">'
            f"{escape(item.title)}</a></li>"
            for item in request.chapters
        )
        return (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<!DOCTYPE html>\n"
            '<html xmlns="http://www.w3.org/1999/xhtml" '
            'xmlns:epub="http://www.idpf.org/2007/ops" '
            f'xml:lang="{escape(self.language)}">\n'
            "<head><title>目录</title></head>\n"
            "<body>\n"
            '  <nav epub:type="toc" id="toc">\n'
            "    <h1>目录</h1>\n"
            "    <ol>\n"
            f"{items}\n"
            "    </ol>\n"
            "  </nav>\n"
            "</body>\n"
            "</html>\n"
        )

    def _ncx(self, request: ExportRequest, book_id: str) -> str:
        """EPUB 2 兼容的 NCX 目录。"""
        points = "\n".join(
            f'    <navPoint id="navPoint-{item.index + 1}" playOrder="{item.index + 1}">\n'
            f"      <navLabel><text>{escape(item.title)}</text></navLabel>\n"
            f'      <content src="text/{self._chapter_filename(item.index)}"/>\n'
            "    </navPoint>"
            for item in request.chapters
        )
        return (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">\n'
            "  <head>\n"
            f'    <meta name="dtb:uid" content="{escape(book_id)}"/>\n'
            '    <meta name="dtb:depth" content="1"/>\n'
            "  </head>\n"
            f"  <docTitle><text>{escape(request.book.name)}</text></docTitle>\n"
            "  <navMap>\n"
            f"{points}\n"
            "  </navMap>\n"
            "</ncx>\n"
        )

    def _cover_page(self, image_href: str) -> str:
        """独立封面页。"""
        return (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<!DOCTYPE html>\n"
            '<html xmlns="http://www.w3.org/1999/xhtml" '
            f'xml:lang="{escape(self.language)}">\n'
            "<head><title>封面</title>"
            "<style>body{margin:0;text-align:center}img{max-width:100%;height:auto}</style>"
            "</head>\n"
            f'<body><img src="{escape(image_href)}" alt="封面"/></body>\n'
            "</html>\n"
        )

    def _chapter_xhtml(self, title: str, text: str) -> str:
        """单章 XHTML。

        正文按行拆成 ``<p>`` —— 阅读器的排版与检索都依赖段落结构，
        整章塞进一个 ``<p>`` 会让行距与缩进全部失效。
        """
        paragraphs = [line.strip() for line in text.split("\n") if line.strip()]
        if not paragraphs:
            paragraphs = [""]
        body = "\n".join(f"    <p>{escape(line)}</p>" for line in paragraphs)
        return (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<!DOCTYPE html>\n"
            '<html xmlns="http://www.w3.org/1999/xhtml" '
            f'xml:lang="{escape(self.language)}">\n'
            "<head>\n"
            f"  <title>{escape(title)}</title>\n"
            '  <link rel="stylesheet" type="text/css" href="../style.css"/>\n'
            "</head>\n"
            "<body>\n"
            f"  <h1>{escape(title)}</h1>\n"
            f"{body}\n"
            "</body>\n"
            "</html>\n"
        )
