"""Legado 书源 JSON 的结构定义。

**这是依据公开的规则格式独立实现的解析模型，不是对 Legado 源码的移植。**

字段名保持与 Legado 书源 JSON 一致（camelCase），因为导入时需要原样读取；
内部一律转成 ``inkflow_core`` 的模型。

未知字段一律保留（``extra="allow"``）—— 书源生态里存在大量自定义字段，
严格校验会让用户的书源无法导入。
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

__all__ = [
    "LegadoBookInfoRule",
    "LegadoBookSource",
    "LegadoContentRule",
    "LegadoSearchRule",
    "LegadoTocRule",
]


class _LenientModel(BaseModel):
    """允许未知字段的基类。"""

    model_config = ConfigDict(extra="allow", populate_by_name=True)


class LegadoSearchRule(_LenientModel):
    """``ruleSearch``：搜索页解析规则。"""

    bookList: str = ""
    name: str = ""
    author: str = ""
    kind: str = ""
    intro: str = ""
    coverUrl: str = ""
    bookUrl: str = ""
    lastChapter: str = ""
    wordCount: str = ""


class LegadoBookInfoRule(_LenientModel):
    """``ruleBookInfo``：详情页解析规则。"""

    init: str = ""
    name: str = ""
    author: str = ""
    kind: str = ""
    intro: str = ""
    coverUrl: str = ""
    tocUrl: str = ""
    lastChapter: str = ""
    wordCount: str = ""
    canReName: str = ""


class LegadoTocRule(_LenientModel):
    """``ruleToc``：目录页解析规则。"""

    chapterList: str = ""
    chapterName: str = ""
    chapterUrl: str = ""
    isVip: str = ""
    updateTime: str = ""
    nextTocUrl: str = ""
    #: 目录前置处理（Legado 允许在这里塞 JS）
    preUpdateJs: str = ""


class LegadoContentRule(_LenientModel):
    """``ruleContent``：正文页解析规则。"""

    content: str = ""
    nextContentUrl: str = ""
    #: 是否替换正文中的标题
    replaceRegex: str = ""
    #: 正文前置处理（可能含 JS）
    webJs: str = ""
    sourceRegex: str = ""


class LegadoBookSource(_LenientModel):
    """一个完整的 Legado 书源。"""

    bookSourceName: str
    bookSourceUrl: str

    bookSourceGroup: str = ""
    bookSourceComment: str = ""
    bookSourceType: int = 0

    enabled: bool = True
    enabledExplore: bool = False

    searchUrl: str = ""
    exploreUrl: str = ""

    ruleSearch: LegadoSearchRule = Field(default_factory=LegadoSearchRule)
    ruleBookInfo: LegadoBookInfoRule = Field(default_factory=LegadoBookInfoRule)
    ruleToc: LegadoTocRule = Field(default_factory=LegadoTocRule)
    ruleContent: LegadoContentRule = Field(default_factory=LegadoContentRule)

    #: 请求头，JSON 字符串
    header: str = ""

    loginUrl: str = ""
    loginUi: str = ""
    loginCheckJs: str = ""

    #: 书源权重，Legado 里叫 customOrder
    customOrder: int = 0

    lastUpdateTime: int = 0
    respondTime: int = 0

    #: 书源声明的并发 / 限速（部分书源带这些扩展字段）
    concurrentRate: str = ""

    @field_validator("bookSourceUrl")
    @classmethod
    def _strip(cls, value: str) -> str:
        return value.rstrip("/")

    @property
    def headers(self) -> dict[str, str]:
        """解析 ``header`` 字段里的 JSON 请求头。

        书源里这个字段经常是空串或半截 JSON，解析失败时返回空字典
        而不是抛错 —— 头部缺失通常不影响搜索，但导入失败会。
        """
        if not self.header.strip():
            return {}
        try:
            parsed = json.loads(self.header)
        except json.JSONDecodeError:
            return {}
        if not isinstance(parsed, dict):
            return {}
        return {str(k): str(v) for k, v in parsed.items()}

    @property
    def search_enabled(self) -> bool:
        return bool(self.searchUrl.strip())

    @property
    def explore_enabled(self) -> bool:
        return bool(self.exploreUrl.strip())

    def uses_js(self) -> bool:
        """书源是否含 JavaScript（决定兼容等级）。

        规则里出现 ``<js>`` 标签或 ``@js:`` 前缀即视为需要 JS 运行时。
        """
        haystacks: list[str] = [
            self.searchUrl,
            self.exploreUrl,
            self.ruleToc.preUpdateJs,
            self.ruleContent.webJs,
            self.loginCheckJs,
        ]
        for rule in (self.ruleSearch, self.ruleBookInfo, self.ruleToc, self.ruleContent):
            haystacks.extend(
                str(value) for value in rule.model_dump().values() if isinstance(value, str)
            )
        return any(
            "<js>" in text or "@js:" in text or "java." in text for text in haystacks if text
        )

    def needs_browser(self) -> bool:
        """书源是否声明需要浏览器渲染。"""
        return "webView" in self.ruleToc.preUpdateJs or "webView" in self.ruleContent.webJs

    def raw_dict(self) -> dict[str, Any]:
        """还原为字典（含未知字段），用于持久化。"""
        return self.model_dump()
