"""书籍路由：详情、目录、正文、导出。"""

from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import APIRouter, Query

from inkflow_api.deps import StateDep
from inkflow_api.schemas import (
    BookDetailResponse,
    BookListResponse,
    ChapterContentResponse,
    ChapterListResponse,
    ExportRequestModel,
    ExportResponse,
)
from inkflow_core.errors import ErrorCode, NotFoundError, SourceError
from inkflow_core.models import Chapter, ChapterContent
from inkflow_core.utils import new_chapter_id
from inkflow_export import (
    ExportChapter,
    ExportRequest,
    available_formats,
    get_exporter,
    sanitize_filename,
)

__all__ = ["router"]

router = APIRouter(prefix="/api/v1/books", tags=["books"])


@router.get("", response_model=BookListResponse, summary="书库列表")
async def list_books(
    state: StateDep,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> BookListResponse:
    """按更新时间倒序列出已入库的书籍。"""
    items = state.library.list_books(limit=limit, offset=offset)
    return BookListResponse(
        items=items,
        total=state.library.count_books(),
        limit=limit,
        offset=offset,
    )


@router.get("/{book_id}", response_model=BookDetailResponse, summary="书籍详情")
async def get_book(state: StateDep, book_id: str) -> BookDetailResponse:
    """书籍详情，含来源信息与章节统计。

    Raises:
        NotFoundError: 书籍不存在。
    """
    book = state.library.get_book(book_id)
    chapters = state.library.get_chapters(book_id)

    source = None
    try:
        source = state.library.get_source(book.source_id)
    except NotFoundError:
        # 书源被删除后书籍仍应可读，来源信息降级为 None
        source = None

    return BookDetailResponse(
        book=book,
        source=source,
        chapter_count=len(chapters),
        downloaded_count=sum(1 for c in chapters if c.downloaded),
    )


@router.get("/{book_id}/chapters", response_model=ChapterListResponse, summary="获取目录")
async def get_chapters(
    state: StateDep,
    book_id: str,
    refresh: bool = Query(False, description="是否重新从书源抓取目录"),
) -> ChapterListResponse:
    """获取目录。

    默认读本地缓存；``refresh=true`` 时重新抓取并整体替换。

    Raises:
        NotFoundError: 书籍不存在。
        SourceError: 重新抓取时书源返回异常。
    """
    book = state.library.get_book(book_id)

    if refresh:
        adapter = state.registry.get(book.source_id)
        remote = await adapter.chapters(book.source_book_url)
        if not remote:
            raise SourceError(
                "书源未返回任何章节，规则可能已失效",
                code=ErrorCode.CHAPTER_PARSE_FAILED,
                details={"book_id": book_id, "source_id": book.source_id},
            )

        chapters = [
            Chapter(
                id=new_chapter_id(),
                book_id=book_id,
                index=item.index,
                name=item.name,
                url=item.url,
                is_vip=item.is_vip,
            )
            for item in remote
        ]
        state.library.replace_chapters(book_id, chapters)

    chapters = state.library.get_chapters(book_id)
    return ChapterListResponse(book_id=book_id, chapters=chapters, total=len(chapters))


@router.get(
    "/{book_id}/chapters/{chapter_id}",
    response_model=ChapterContentResponse,
    summary="获取章节正文",
)
async def get_chapter_content(
    state: StateDep,
    book_id: str,
    chapter_id: str,
    refresh: bool = Query(False, description="是否强制重新抓取"),
) -> ChapterContentResponse:
    """获取章节正文。

    优先读本地缓存；未下载或 ``refresh=true`` 时向书源抓取并入库。

    Raises:
        NotFoundError: 书籍或章节不存在。
        SourceError: 书源抓取失败。
    """
    book = state.library.get_book(book_id)
    chapter = state.library.get_chapter(chapter_id)
    if chapter.book_id != book_id:
        raise NotFoundError(
            "章节不属于该书",
            details={"book_id": book_id, "chapter_id": chapter_id},
        )

    content: ChapterContent | None = None if refresh else state.library.get_content(chapter_id)

    if content is None:
        adapter = state.registry.get(book.source_id)
        result = await adapter.content(chapter.url)
        content = ChapterContent(
            chapter_id=chapter_id,
            raw_content=result.raw or result.content,
            clean_content=result.content,
            content_hash="",
        )
        state.library.save_content(content)
        state.library.mark_chapter_downloaded(chapter_id, content.content_hash)
        chapter = state.library.get_chapter(chapter_id)

    return ChapterContentResponse(chapter=chapter, content=content)


@router.post("/{book_id}/export", response_model=ExportResponse, summary="导出书籍")
async def export_book(
    state: StateDep,
    book_id: str,
    payload: ExportRequestModel,
) -> ExportResponse:
    """把已下载的章节导出为 TXT / EPUB / Markdown。

    只导出**已下载**的章节；缺失的章节会被跳过而不是产生空章节。

    Raises:
        NotFoundError: 书籍不存在。
        SourceError: 没有可导出的内容，或格式不支持。
    """
    book = state.library.get_book(book_id)
    all_chapters = state.library.get_chapters(book_id)
    if not all_chapters:
        raise SourceError(
            "该书还没有目录，请先获取目录",
            code=ErrorCode.BOOK_NO_CHAPTERS,
            details={"book_id": book_id},
        )

    last = len(all_chapters) - 1
    start = max(0, min(payload.start_chapter, last))
    end = last if payload.end_chapter is None else max(start, min(payload.end_chapter, last))
    selected = [c for c in all_chapters if start <= c.index <= end]

    contents = state.library.get_contents([c.id for c in selected])
    if not contents:
        raise SourceError(
            "所选范围内没有已下载的章节",
            code=ErrorCode.EXPORT_FAILED,
            details={"book_id": book_id, "start": start, "end": end},
        )

    try:
        exporter = get_exporter(payload.format)
    except ValueError as exc:
        raise SourceError(
            str(exc),
            code=ErrorCode.EXPORT_FAILED,
            details={"format": payload.format, "available": available_formats()},
        ) from exc

    output_path = (
        Path(payload.output_path)
        if payload.output_path
        else state.paths.exports_dir / f"{sanitize_filename(book.name)}{exporter.extension}"
    )

    source_name = ""
    try:
        source_name = state.library.get_source(book.source_id).name
    except NotFoundError:
        source_name = ""

    request = ExportRequest(
        book=book,
        chapters=[ExportChapter(chapter=c, content=contents.get(c.id)) for c in selected],
        output_path=output_path,
        source_name=source_name,
        filename_template=state.settings.export.filename_template,
    )
    written = await asyncio.to_thread(exporter.export, request)

    return ExportResponse(
        book_id=book_id,
        format=payload.format,
        output_path=str(written),
        chapter_count=len(selected),
    )
