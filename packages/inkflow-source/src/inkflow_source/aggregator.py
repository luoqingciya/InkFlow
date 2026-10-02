"""搜索聚合（规划书 §19、§20、§21）。

    关键词
      ↓
    Source Manager
      ↓  并行请求多个 Source
    Result Aggregator
      ↓  按 (归一化书名, 归一化作者) 归并
      ↓  评分排序
    返回

**关键约束**：书源优先级不决定唯一结果。同一本书在多个来源命中时，
所有来源都保留在 ``SearchResult.sources`` 里 —— 不同来源的更新速度、
章节数、正文质量、可用性都不同，选择权属于用户。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from inkflow_core.models import (
    BookResult,
    BookSource,
    SearchResult,
    SourceRef,
)
from inkflow_core.normalize import normalize_author, normalize_book_name
from inkflow_source.registry import SourceRegistry

__all__ = ["SearchAggregator", "SourceOutcome", "score_book"]


@dataclass(slots=True)
class SourceOutcome:
    """单个书源的搜索产出。"""

    source: BookSource
    results: list[BookResult] = field(default_factory=list)
    elapsed: float = 0.0
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


def score_book(
    keyword: str,
    book: BookResult,
    source: BookSource,
    *,
    elapsed: float = 0.0,
) -> float:
    """给单个候选打分（规划书 §21）。

    维度：匹配度、源权重、响应速度、信息完整度。
    分数只用于**排序**，不代表内容质量。
    """
    key = normalize_book_name(keyword)
    name = normalize_book_name(book.name)

    if key == name:
        score = 50.0
    elif key and (key in name or name in key):
        score = 35.0
    else:
        score = 30.0 * SequenceMatcher(None, key, name).ratio()

    # 源权重：priority 范围 -100 ~ 100，折算成 -10 ~ +10
    score += source.priority * 0.1

    # 响应速度：1 秒内满分，之后线性衰减到 0
    score += max(0.0, 10.0 - elapsed)

    # 信息完整度
    if book.latest_chapter:
        score += 3.0
    if book.author:
        score += 1.0
    if book.cover_url:
        score += 1.0
    if book.intro:
        score += 1.0

    return score


class SearchAggregator:
    """跨书源搜索并聚合结果。

    Args:
        registry: 书源注册表。
        timeout: 单个书源的搜索超时（秒）。超时视为该源失败，不影响其他源。
    """

    def __init__(self, registry: SourceRegistry, *, timeout: float = 25.0) -> None:
        self.registry = registry
        self.timeout = timeout

    async def search(
        self,
        keyword: str,
        *,
        page: int = 1,
        source_ids: list[str] | None = None,
        limit: int | None = None,
    ) -> list[SearchResult]:
        """并行搜索多个书源并返回去重排序后的结果。

        Args:
            keyword: 搜索关键词。
            page: 页码，透传给各书源。
            source_ids: 限定书源；``None`` 表示全部可搜索书源。
            limit: 返回条数上限。

        Raises:
            SourceError: 没有任何可用书源。
        """
        adapters = self.registry.resolve(source_ids)
        if not adapters:
            from inkflow_core.errors import ErrorCode, SourceError

            raise SourceError(
                "没有可用的书源，请先导入并启用书源",
                code=ErrorCode.SEARCH_NO_SOURCE,
            )

        results, _ = await self.search_detailed(
            keyword, page=page, source_ids=source_ids, limit=limit
        )
        return results

    async def search_detailed(
        self,
        keyword: str,
        *,
        page: int = 1,
        source_ids: list[str] | None = None,
        limit: int | None = None,
    ) -> tuple[list[SearchResult], dict[str, str]]:
        """搜索并返回 ``(结果, 各源错误)``。

        API 层需要知道「哪个书源失败了」，否则用户看到结果变少却无从判断原因。

        Raises:
            SourceError: 没有任何可用书源。
        """
        adapters = self.registry.resolve(source_ids)
        if not adapters:
            from inkflow_core.errors import ErrorCode, SourceError

            raise SourceError(
                "没有可用的书源，请先导入并启用书源",
                code=ErrorCode.SEARCH_NO_SOURCE,
            )

        outcomes = await asyncio.gather(
            *(self.query_source(adapter, keyword, page) for adapter in adapters)
        )
        merged = self.merge(keyword, outcomes)
        if limit:
            merged = merged[:limit]
        # ``error`` 在类型上是可选的；只有真正失败且带消息的源才进这张表
        errors = {
            outcome.source.id: outcome.error
            for outcome in outcomes
            if not outcome.ok and outcome.error is not None
        }
        return merged, errors

    # -- 内部 --------------------------------------------------------------

    async def query_source(self, adapter: object, keyword: str, page: int) -> SourceOutcome:
        """查询单个书源。任何异常都被收敛为 ``SourceOutcome.error``。"""
        import time

        source: BookSource = adapter.source  # type: ignore[attr-defined]
        started = time.monotonic()
        try:
            results = await asyncio.wait_for(
                adapter.search(keyword, page),  # type: ignore[attr-defined]
                timeout=self.timeout,
            )
        except TimeoutError:
            return SourceOutcome(
                source=source,
                elapsed=time.monotonic() - started,
                error=f"搜索超时（>{self.timeout:g}s）",
            )
        except Exception as exc:
            return SourceOutcome(
                source=source,
                elapsed=time.monotonic() - started,
                error=f"{type(exc).__name__}: {exc}",
            )
        return SourceOutcome(
            source=source,
            results=list(results),
            elapsed=time.monotonic() - started,
        )

    def merge(self, keyword: str, outcomes: list[SourceOutcome]) -> list[SearchResult]:
        """把各源结果按书籍身份归并。"""
        # 第一轮：按 (归一化书名, 归一化作者) 分组
        groups: dict[tuple[str, str], list[tuple[BookResult, BookSource, float]]] = {}
        for outcome in outcomes:
            if not outcome.ok:
                continue
            for book in outcome.results:
                key = (
                    normalize_book_name(book.name),
                    normalize_author(book.author),
                )
                groups.setdefault(key, []).append((book, outcome.source, outcome.elapsed))

        # 第二轮：把「无作者」的分组并到同名且有作者的分组（§19 的常见情况）
        by_name: dict[str, list[tuple[str, str]]] = {}
        for name_key, author_key in groups:
            by_name.setdefault(name_key, []).append((name_key, author_key))
        for keys in by_name.values():
            anonymous = [k for k in keys if not k[1]]
            identified = [k for k in keys if k[1]]
            if not anonymous or not identified:
                continue
            target = identified[0]
            for key in anonymous:
                groups[target].extend(groups.pop(key))

        results = [self._build_result(keyword, members) for members in groups.values()]
        results.sort(key=lambda r: r.score, reverse=True)
        return results

    def _build_result(
        self,
        keyword: str,
        members: list[tuple[BookResult, BookSource, float]],
    ) -> SearchResult:
        """把同一本书的多个来源合并成一条搜索结果。"""
        # 信息最全的那条作为展示主记录
        primary_book, primary_source, primary_elapsed = max(
            members,
            key=lambda item: sum(
                1
                for value in (
                    item[0].author,
                    item[0].intro,
                    item[0].cover_url,
                    item[0].latest_chapter,
                )
                if value
            ),
        )

        refs: list[SourceRef] = []
        for book, source, elapsed in members:
            refs.append(
                SourceRef(
                    source_id=source.id,
                    source_name=source.name,
                    book_id="",  # 入库后由 BookRepository 回填
                    book_url=book.book_url,
                    latest_chapter=book.latest_chapter,
                    score=score_book(keyword, book, source, elapsed=elapsed),
                )
            )
        refs.sort(key=lambda r: r.score, reverse=True)

        return SearchResult(
            name=primary_book.name,
            author=primary_book.author,
            intro=primary_book.intro,
            cover_url=primary_book.cover_url,
            category=primary_book.category,
            status=primary_book.status,
            sources=refs,
            score=score_book(keyword, primary_book, primary_source, elapsed=primary_elapsed),
        )
