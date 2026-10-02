"""书源引擎的统一输出契约（规划书 §17、§20）。

任何 SourceAdapter —— 原生、Legado JSON、Legado JS、浏览器 —— 都必须返回
这里的类型。业务层因此永远不需要知道数据是从 CSS Selector、XPath 还是
一段 JavaScript 里来的。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from inkflow_core.normalize import normalize_book_name

__all__ = [
    "BookResult",
    "ChapterResult",
    "ContentResult",
    "SearchResult",
    "SourceRef",
]


class BookResult(BaseModel):
    """书源返回的书籍详情。"""

    model_config = ConfigDict(extra="ignore")

    name: str
    author: str | None = None

    intro: str | None = None
    cover_url: str | None = None

    category: str | None = None
    status: str | None = None

    word_count: int | None = None
    latest_chapter: str | None = None

    #: 该书在**本来源**下的详情页地址
    book_url: str

    #: 书源自定义字段，透传不解释
    extra: dict[str, Any] = Field(default_factory=dict)


class ChapterResult(BaseModel):
    """书源返回的目录条目。"""

    model_config = ConfigDict(extra="ignore")

    index: int = Field(ge=0)
    name: str
    url: str
    is_vip: bool = False


class ContentResult(BaseModel):
    """书源返回的章节正文。"""

    model_config = ConfigDict(extra="ignore")

    #: 清洗后的正文
    content: str

    #: 清洗前的原始提取结果，保留用于回溯
    raw: str | None = None

    chapter_name: str | None = None

    #: 正文分页的下一页地址；为 None 表示已到末页
    next_url: str | None = None

    #: 正文内嵌图片地址
    images: list[str] = Field(default_factory=list)


class SourceRef(BaseModel):
    """同一本书在某个书源下的引用（规划书 §19）。"""

    model_config = ConfigDict(extra="ignore")

    source_id: str
    source_name: str
    book_id: str
    book_url: str
    latest_chapter: str | None = None
    #: 该书源单独的评分，用于展示「哪个来源更全」
    score: float = 0.0


class SearchResult(BaseModel):
    """聚合去重后的单条搜索结果。

    同一本书在多个书源命中时会合并成**一条** ``SearchResult``，
    但所有来源都保留在 ``sources`` 中 —— 不同来源的更新速度与正文质量
    不同，交由用户决定用哪个。
    """

    model_config = ConfigDict(extra="ignore")

    name: str
    author: str | None = None
    normalized_name: str = ""

    intro: str | None = None
    cover_url: str | None = None
    category: str | None = None
    status: str | None = None

    #: 至少一个来源，第一个为默认来源
    sources: list[SourceRef] = Field(default_factory=list)

    #: 综合评分（规划书 §21）
    score: float = 0.0

    def model_post_init(self, __context: Any) -> None:
        if not self.normalized_name:
            self.normalized_name = normalize_book_name(self.name)

    @property
    def primary(self) -> SourceRef:
        """默认来源。"""
        if not self.sources:
            raise ValueError(f"搜索结果 {self.name!r} 没有任何来源")
        return self.sources[0]

    @property
    def book_id(self) -> str:
        """默认来源对应的 Book.id。"""
        return self.primary.book_id
