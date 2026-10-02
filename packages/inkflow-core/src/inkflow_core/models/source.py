"""书源模型。

对应规划书 §9.1。书源是**不可信输入**：这里的字段只描述「是什么」，
不承载任何执行逻辑，执行由 inkflow-source / inkflow-legado 负责。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from inkflow_core.models.enums import (
    CompatibilityLevel,
    SourceFormat,
    SourceType,
)
from inkflow_core.utils import utcnow

__all__ = ["BookSource", "RequestConfig", "SourceMeta"]


class RequestConfig(BaseModel):
    """书源级请求约束（规划书 §15）。

    该配置只会**收紧**全局限制，不会放宽 —— 最终并发取
    ``min(source.concurrency, global_concurrency, domain_concurrency)``。
    """

    model_config = ConfigDict(extra="forbid")

    concurrency: int = Field(default=3, ge=1, le=32)
    requests_per_second: float = Field(default=2.0, gt=0)
    timeout: float = Field(default=20.0, gt=0)
    retry: int = Field(default=3, ge=0, le=10)

    headers: dict[str, str] = Field(default_factory=dict)
    user_agent: str | None = None


class SourceMeta(BaseModel):
    """书源元信息（规划书 §40），用于书源管理与兼容性追踪。"""

    model_config = ConfigDict(extra="allow")

    author: str | None = None
    version: str | None = None
    homepage: str | None = None
    license: str | None = None
    last_updated: str | None = None
    description: str | None = None
    # 是否声明需要浏览器渲染（决定是否允许升级到 L3）
    requires_browser: bool = False


class BookSource(BaseModel):
    """一个可执行的书源定义。"""

    model_config = ConfigDict(extra="ignore")

    id: str
    name: str
    url: str

    enabled: bool = True
    priority: int = Field(default=0, ge=-100, le=100)

    source_type: SourceType
    source_format: SourceFormat
    compatibility_level: CompatibilityLevel = CompatibilityLevel.L0

    # Legado 书源自带的规则版本号，用于兼容层分支
    rule_version: str = "1.0"

    enabled_search: bool = True
    enabled_explore: bool = False

    request: RequestConfig = Field(default_factory=RequestConfig)
    meta: SourceMeta = Field(default_factory=SourceMeta)

    # 原始书源内容。保留原文才能在不重新导入的情况下重编译规则。
    raw: dict[str, Any] = Field(default_factory=dict)

    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

    @field_validator("url")
    @classmethod
    def _strip_trailing_slash(cls, value: str) -> str:
        return value.rstrip("/")

    @property
    def is_legado(self) -> bool:
        return self.source_type is SourceType.LEGADO

    def supports_level(self, level: CompatibilityLevel) -> bool:
        """判断书源是否达到指定兼容等级。

        等级是有序的，L2 书源同时满足 L0 / L1。
        """
        order = [
            CompatibilityLevel.L0,
            CompatibilityLevel.L1,
            CompatibilityLevel.L2,
            CompatibilityLevel.L3,
        ]
        if self.compatibility_level is CompatibilityLevel.NATIVE:
            return level is CompatibilityLevel.NATIVE
        try:
            return order.index(self.compatibility_level) >= order.index(level)
        except ValueError:
            return False
