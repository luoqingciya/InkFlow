"""章节与章节正文模型（规划书 §11、§12）。

正文与元数据**刻意分离**：修改清洗算法时可以只重算 ``clean_content``，
不必回访来源网站，也不必动目录结构。
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from inkflow_core.normalize import content_hash
from inkflow_core.utils import utcnow

__all__ = ["Chapter", "ChapterContent"]


class Chapter(BaseModel):
    """目录中的一个章节条目。"""

    model_config = ConfigDict(extra="ignore")

    id: str

    book_id: str

    index: int = Field(ge=0)
    name: str
    url: str

    is_vip: bool = False

    downloaded: bool = False

    # 正文内容的 SHA256，用于判断是否已变化
    content_hash: str | None = None

    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class ChapterContent(BaseModel):
    """章节正文。

    ``raw_content`` 是来源页面的原始提取结果，``clean_content`` 是经
    ContentNormalizer 处理后的标准正文。两者都保留 —— 清洗规则改坏时
    还能回到原始数据重跑，不必重新抓取。
    """

    model_config = ConfigDict(extra="ignore")

    chapter_id: str

    raw_content: str
    clean_content: str

    content_hash: str
    fetched_at: datetime = Field(default_factory=utcnow)

    @model_validator(mode="after")
    def _ensure_hash(self) -> ChapterContent:
        if not self.content_hash:
            self.content_hash = content_hash(self.clean_content or self.raw_content)
        return self

    @property
    def word_count(self) -> int:
        """粗略字数：按非空白字符计。"""
        return len("".join(self.clean_content.split()))
