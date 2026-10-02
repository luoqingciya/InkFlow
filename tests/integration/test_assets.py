"""封面与正文插图的资源下载测试。

mock 站点对 ``/cover/`` 与 ``/img/`` 下的任何路径都返回同一张 1×1 PNG，
所以这里跑的是**真实的下载 + 嵌入**，而不是把下载器 mock 掉 ——
这一层最怕的就是「函数被调用了」和「文件真的生成了」之间的差距。
"""

from __future__ import annotations

import zipfile

import pytest

from inkflow_api.state import AppState
from tests.conftest import _Library, wait_for_terminal

pytestmark = pytest.mark.integration


def _run_task(library: _Library, fmt: str = "epub") -> dict:
    task_id = library.client.post(
        "/api/v1/tasks", json={"book_id": library.book_id, "output_format": fmt}
    ).json()["id"]
    return wait_for_terminal(library.client, task_id)


# ================================================================ 封面


def test_cover_is_embedded_in_epub(library: _Library) -> None:
    """封面要真的进到 EPUB 里 —— 只下载不嵌入等于没做。

    断言的是 zip 里存在封面条目，而不是「下载函数被调用了」。
    """
    task = _run_task(library)

    with zipfile.ZipFile(task["output_path"]) as zf:
        names = zf.namelist()

    assert any(name.startswith("OEBPS/images/cover.") for name in names), names


def test_cover_is_declared_in_opf(library: _Library) -> None:
    """EPUB 的 content.opf 要把封面登记成 meta —— 阅读器靠它显示封面。"""
    task = _run_task(library)

    with zipfile.ZipFile(task["output_path"]) as zf:
        opf = zf.read("OEBPS/content.opf").decode("utf-8")

    assert "cover-image" in opf
    assert "images/cover." in opf


async def test_missing_cover_does_not_fail_export(
    state: AppState, library: _Library, mock_site: str
) -> None:
    """封面拿不到时返回 None —— 它是锦上添花，不该带走整本书的导出。"""
    book = state.tasks.library.get_book(library.book_id)
    book.cover_url = f"{mock_site}/missing-cover.jpg"  # 非 /cover/ 前缀 → 404

    assert await state.tasks._fetch_cover(book) is None


async def test_empty_cover_url_is_skipped(state: AppState, library: _Library) -> None:
    """没有封面地址时直接跳过，连请求都不发。"""
    book = state.tasks.library.get_book(library.book_id)
    book.cover_url = ""

    assert await state.tasks._fetch_cover(book) is None


async def test_non_image_cover_is_rejected(
    state: AppState, library: _Library, mock_site: str
) -> None:
    """地址指向 HTML 页面时不该当成封面 —— 否则 EPUB 里会塞进一段网页。"""
    book = state.tasks.library.get_book(library.book_id)
    book.cover_url = f"{mock_site}/book/1"

    assert await state.tasks._fetch_cover(book) is None


async def test_cover_media_type_is_detected(
    state: AppState, library: _Library, mock_site: str
) -> None:
    """MIME 类型取自响应头，用于决定 EPUB 里的文件后缀。"""
    book = state.tasks.library.get_book(library.book_id)
    book.cover_url = f"{mock_site}/cover/1.jpg"

    cover = await state.tasks._fetch_cover(book)

    assert cover is not None
    content, media_type = cover
    assert content
    assert media_type == "image/png"


# ================================================================ 正文插图


def test_inline_images_are_saved_to_book_dir(library: _Library, state: AppState) -> None:
    """正文插图要落到书籍目录。

    图片地址只存在于 ``raw_content``（清洗后的正文是纯文本，不含 img），
    所以这一步也顺带验证了「从原始 HTML 提取地址」这条路径是通的。
    """
    _run_task(library)

    images = list((state.paths.books_dir / library.book_id / "images").glob("*"))

    assert images, "正文里的插图没有被下载"


def test_saved_image_has_real_bytes(library: _Library, state: AppState) -> None:
    """落盘的是图片字节，不是空文件或错误页面。"""
    _run_task(library)

    images = list((state.paths.books_dir / library.book_id / "images").glob("*"))

    assert images
    assert all(image.stat().st_size > 0 for image in images)


def test_image_suffix_comes_from_url(library: _Library, state: AppState) -> None:
    """扩展名从地址推断，便于人直接打开查看。"""
    _run_task(library)

    names = [image.name for image in (state.paths.books_dir / library.book_id / "images").glob("*")]

    assert names
    assert all(name.endswith(".png") for name in names), names


def test_images_are_not_refetched_on_rerun(library: _Library, state: AppState) -> None:
    """重复导出不重复下载 —— 已经存在的文件直接跳过。"""
    _run_task(library)
    directory = state.paths.books_dir / library.book_id / "images"
    first = {image.name: image.stat().st_mtime_ns for image in directory.glob("*")}

    _run_task(library)
    second = {image.name: image.stat().st_mtime_ns for image in directory.glob("*")}

    assert first == second
