"""书籍模型（规划书 §10）。"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from inkflow_core.normalize import normalize_book_name
from inkflow_core.utils import utcnow

__all__ = ["Book"]


class Book(BaseModel):
    """一本书在某个书源下的记录。

    注意：``Book`` 是**书源维度**的，同一本书在三个书源下就是三条 ``Book``。
    跨书源的同一性由 Book Identity Resolver 通过 ``normalized_name`` +
    ``author`` 关联（规划书 §19），但**不合并**这些记录 ——
    不同来源的更新速度、章节数、正文质量都不同，必须保留。
    """

    model_config = ConfigDict(extra="ignore")

    id: str

    name: str
    author: str | None = None

    intro: str | None = None
    cover_url: str | None = None

    category: str | None = None
    status: str | None = None

    source_id: str
    source_book_url: str

    word_count: int | None = None
    latest_chapter: str | None = None

    # 归一化书名，用于跨书源去重；未显式提供时自动计算
    normalized_name: str | None = None

    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

    @model_validator(mode="after")
    def _fill_normalized_name(self) -> Book:
        if not self.normalized_name:
            self.normalized_name = normalize_book_name(self.name)
        return self
