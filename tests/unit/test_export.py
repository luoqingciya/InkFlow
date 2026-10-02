"""导出器测试。"""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from inkflow_core.models import Book, Chapter, ChapterContent
from inkflow_export import (
    EpubExporter,
    ExportChapter,
    ExportRequest,
    MarkdownExporter,
    TxtExporter,
    available_formats,
    get_exporter,
    sanitize_filename,
)

pytestmark = pytest.mark.unit


@pytest.fixture
def request_factory(tmp_path: Path):
    """构造导出请求。"""

    def build(count: int = 3, fmt_path: str = "book.out") -> ExportRequest:
        book = Book(
            id="bk_test",
            name="三体",
            author="刘慈欣",
            intro="测试用简介",
            source_id="src_test",
            source_book_url="https://example.com/book/1",
        )
        chapters = []
        for index in range(count):
            chapter = Chapter(
                id=f"ch_{index}",
                book_id=book.id,
                index=index,
                name=f"第{index + 1}章 测试章节",
                url=f"https://example.com/chapter/{index}",
            )
            content = ChapterContent(
                chapter_id=chapter.id,
                raw_content="raw",
                clean_content=f"这是第{index + 1}章的正文。\n\n第二段内容。",
                content_hash="",
            )
            chapters.append(ExportChapter(chapter=chapter, content=content))
        return ExportRequest(
            book=book,
            chapters=chapters,
            output_path=tmp_path / fmt_path,
            source_name="Mock 书源",
        )

    return build


# ---------------------------------------------------------------- 文件名


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("三体", "三体"),
        ("a/b:c*d?", "a_b_c_d_"),
        ("  trailing  ", "trailing"),
        ("CON", "_CON"),
        ("", "untitled"),
    ],
)
def test_sanitize_filename(raw: str, expected: str) -> None:
    """非法字符与 Windows 保留名都要处理掉。"""
    assert sanitize_filename(raw) == expected


def test_sanitize_filename_truncates() -> None:
    assert len(sanitize_filename("书" * 500)) == 120


# ---------------------------------------------------------------- 注册表


def test_builtin_formats_registered() -> None:
    assert set(available_formats()) >= {"txt", "epub", "markdown"}
    assert get_exporter("epub").extension == ".epub"


def test_unknown_format_raises() -> None:
    with pytest.raises(ValueError, match="不支持的导出格式"):
        get_exporter("pdf")


# ---------------------------------------------------------------- TXT


def test_txt_export(request_factory) -> None:
    request = request_factory()
    output = TxtExporter().export(request)

    assert output.exists()
    # utf-8-sig：Windows 记事本靠 BOM 才能正确识别中文
    raw = output.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")

    text = output.read_text(encoding="utf-8-sig")
    assert "三体" in text
    assert "刘慈欣" in text
    assert "第1章 测试章节" in text
    assert "这是第1章的正文。" in text


def test_txt_export_without_header(request_factory) -> None:
    request = request_factory(count=1)
    text = TxtExporter(with_header=False).export(request).read_text(encoding="utf-8-sig")
    assert "作者：" not in text


# ---------------------------------------------------------------- EPUB


def test_epub_structure(request_factory) -> None:
    """EPUB 必须是合法 zip，且 mimetype 是首个未压缩条目。"""
    request = request_factory()
    output = EpubExporter().export(request)

    assert output.exists()
    with zipfile.ZipFile(output) as archive:
        names = archive.namelist()
        assert names[0] == "mimetype"

        info = archive.getinfo("mimetype")
        assert info.compress_type == zipfile.ZIP_STORED
        assert archive.read("mimetype") == b"application/epub+zip"

        assert "META-INF/container.xml" in names
        assert "OEBPS/content.opf" in names
        assert "OEBPS/nav.xhtml" in names
        assert "OEBPS/toc.ncx" in names
        assert "OEBPS/text/chapter-0001.xhtml" in names
        assert "OEBPS/text/chapter-0003.xhtml" in names


def test_epub_metadata_and_content(request_factory) -> None:
    output = EpubExporter().export(request_factory())
    with zipfile.ZipFile(output) as archive:
        opf = archive.read("OEBPS/content.opf").decode("utf-8")
        assert "三体" in opf
        assert "刘慈欣" in opf
        assert "Mock 书源" in opf
        assert 'version="3.0"' in opf

        chapter = archive.read("OEBPS/text/chapter-0001.xhtml").decode("utf-8")
        assert "第1章 测试章节" in chapter
        # 正文按行拆成段落，否则阅读器的缩进与检索都会失效
        assert chapter.count("<p>") == 2


def test_epub_cover_included_when_provided(request_factory) -> None:
    request = request_factory()
    request.cover_bytes = b"\xff\xd8\xff\xe0fake-jpeg"
    request.cover_media_type = "image/jpeg"
    output = EpubExporter().export(request)

    with zipfile.ZipFile(output) as archive:
        names = archive.namelist()
        assert "OEBPS/images/cover.jpg" in names
        assert "OEBPS/cover.xhtml" in names
        assert b"cover-image" in archive.read("OEBPS/content.opf")


def test_epub_without_cover_has_no_cover_entries(request_factory) -> None:
    output = EpubExporter().export(request_factory())
    with zipfile.ZipFile(output) as archive:
        assert not any("cover" in name for name in archive.namelist())


def test_epub_escapes_special_characters(request_factory) -> None:
    """书名里的 XML 特殊字符必须转义，否则文件无法解析。"""
    request = request_factory(count=1)
    request.book.name = '三体 & <script> "测试"'
    output = EpubExporter().export(request)

    with zipfile.ZipFile(output) as archive:
        opf = archive.read("OEBPS/content.opf").decode("utf-8")
        assert "<script>" not in opf
        assert "&amp;" in opf
        assert "&lt;script&gt;" in opf


def test_epub_handles_empty_chapter(request_factory) -> None:
    """空章节也要生成合法 XHTML，不能让导出整体失败。"""
    request = request_factory(count=1)
    request.chapters[0].content.clean_content = ""
    output = EpubExporter().export(request)

    with zipfile.ZipFile(output) as archive:
        chapter = archive.read("OEBPS/text/chapter-0001.xhtml").decode("utf-8")
        assert "<h1>" in chapter


# ---------------------------------------------------------------- Markdown


def test_markdown_export(request_factory) -> None:
    request = request_factory()
    output = MarkdownExporter().export(request)
    text = output.read_text(encoding="utf-8")

    assert text.startswith("---")
    assert 'title: "三体"' in text
    assert "## 目录" in text
    assert "## 第1章 测试章节" in text
