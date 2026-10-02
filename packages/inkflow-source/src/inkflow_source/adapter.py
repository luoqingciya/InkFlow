"""书源适配器契约（规划书 §4.1）。

**这是整个 Source Engine 的收口点。** 无论书源是原生 YAML、Legado JSON、
Legado JS 还是浏览器渲染，业务层只认识这四个方法。

新增一种书源格式 = 新增一个 ``SourceAdapter`` 实现，不修改任何既有代码。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from inkflow_core.models import (
    BookResult,
    BookSource,
    ChapterResult,
    ContentResult,
)

if TYPE_CHECKING:  # pragma: no cover
    from inkflow_source.http import HttpClient

__all__ = ["BaseSourceAdapter", "SourceAdapter"]


@runtime_checkable
class SourceAdapter(Protocol):
    """书源适配器协议。

    实现者需保证：**方法要么返回结果，要么抛 ``InkFlowError``**，
    不允许返回 ``None`` 或吞掉异常。
    """

    source: BookSource

    async def search(self, keyword: str, page: int = 1) -> list[BookResult]:
        """按关键词搜索，返回该书源命中的书籍列表。

        Args:
            keyword: 搜索关键词。
            page: 页码，从 1 开始。

        Returns:
            命中的书籍；无结果时返回空列表（不是异常）。
        """
        ...

    async def book_info(self, book_url: str) -> BookResult:
        """获取书籍详情。

        Args:
            book_url: 该书源内的详情页地址。
        """
        ...

    async def chapters(self, book_url: str) -> list[ChapterResult]:
        """获取目录。

        返回结果必须**按阅读顺序**排列，``index`` 从 0 连续递增。
        分页目录由实现者负责翻页，且必须有页数上限（规划书 §22）。
        """
        ...

    async def content(self, chapter_url: str) -> ContentResult:
        """获取章节正文。"""
        ...

    async def aclose(self) -> None:
        """释放该适配器持有的资源（连接、浏览器上下文等）。"""
        ...


class BaseSourceAdapter(ABC):
    """适配器基类，实现通用的资源持有与释放。

    子类只需实现四个业务方法；``source`` 与 ``http`` 由基类注入。
    """

    def __init__(self, source: BookSource, http: HttpClient | None = None) -> None:
        self.source = source
        self._http = http
        self._closed = False

    @property
    def http(self) -> HttpClient:
        """返回 HTTP 客户端，未注入时按书源配置惰性创建。"""
        if self._http is None:
            from inkflow_source.http import HttpClient

            self._http = HttpClient.from_source(self.source)
        return self._http

    @abstractmethod
    async def search(self, keyword: str, page: int = 1) -> list[BookResult]:
        """按关键词搜索。"""
        raise NotImplementedError

    @abstractmethod
    async def book_info(self, book_url: str) -> BookResult:
        """获取书籍详情。"""
        raise NotImplementedError

    @abstractmethod
    async def chapters(self, book_url: str) -> list[ChapterResult]:
        """获取目录。"""
        raise NotImplementedError

    @abstractmethod
    async def content(self, chapter_url: str) -> ContentResult:
        """获取章节正文。"""
        raise NotImplementedError

    async def aclose(self) -> None:
        """释放连接。幂等，重复调用无副作用。"""
        if self._closed:
            return
        self._closed = True
        if self._http is not None:
            await self._http.aclose()
