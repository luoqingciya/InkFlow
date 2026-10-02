"""搜索路由（规划书 §20）。"""

from __future__ import annotations

from fastapi import APIRouter, Query

from inkflow_api.deps import StateDep
from inkflow_api.schemas import SearchResponse
from inkflow_core.models import Book, SearchResult, SourceRef
from inkflow_core.utils import new_book_id

__all__ = ["router"]

router = APIRouter(prefix="/api/v1", tags=["search"])


@router.get("/search", response_model=SearchResponse, summary="聚合搜索")
async def search(
    state: StateDep,
    q: str = Query(..., min_length=1, description="搜索关键词"),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    sources: str | None = Query(None, description="限定书源 ID，逗号分隔"),
) -> SearchResponse:
    """跨书源搜索并聚合去重。

    同一本书在多个书源命中时只返回一条，但 ``sources`` 里保留全部来源 ——
    不同来源的更新速度与正文质量不同，由用户决定用哪个。

    Raises:
        SourceError: 没有可用书源。
    """
    source_ids = [s.strip() for s in sources.split(",") if s.strip()] if sources else None

    results, errors = await state.aggregator.search_detailed(
        q, page=page, source_ids=source_ids, limit=limit
    )

    # 搜索结果必须先入库，后续的目录 / 下载接口才能按 book_id 引用
    persisted = [_persist(state, result) for result in results]

    return SearchResponse(
        keyword=q,
        items=persisted,
        source_errors=errors,
        total=len(persisted),
    )


def _persist(state: StateDep, result: SearchResult) -> SearchResult:
    """把搜索结果里的各来源写入书库，并回填 ``book_id``。"""
    refs: list[SourceRef] = []
    for ref in result.sources:
        book = Book(
            id=new_book_id(),
            name=result.name,
            author=result.author,
            intro=result.intro,
            cover_url=result.cover_url,
            category=result.category,
            status=result.status,
            source_id=ref.source_id,
            source_book_url=ref.book_url,
            latest_chapter=ref.latest_chapter,
        )
        saved = state.library.upsert_book(book)
        refs.append(
            SourceRef(
                source_id=ref.source_id,
                source_name=ref.source_name,
                book_id=saved.id,
                book_url=ref.book_url,
                latest_chapter=ref.latest_chapter,
                score=ref.score,
            )
        )

    return SearchResult(
        name=result.name,
        author=result.author,
        intro=result.intro,
        cover_url=result.cover_url,
        category=result.category,
        status=result.status,
        sources=refs,
        score=result.score,
    )
