"""原生书源（Level 1）的 YAML 规格（规划书 §5）。

原生书源用声明式 YAML 描述「请求什么、从哪里取什么」，不写代码。
优点是最易维护、性能最高、可类型校验、可用 Python 原生调试。

字段取值语法：

    selector: "h3 > a"        # CSS 或 XPath（以 / 开头视为 XPath）
    attr: text                # text | html | @属性名
    regex: "第(\\d+)章"        # 可选，在取值后再做一次提取
    absolute: true            # 可选，相对 URL 转绝对
"""

from __future__ import annotations

from typing import Any, Literal
from urllib.parse import urljoin

from lxml.html import HtmlElement
from pydantic import BaseModel, ConfigDict, Field

from inkflow_source.parsers import html as html_parser
from inkflow_source.parsers import text as text_parser

__all__ = ["FieldSpec", "ListSpec", "NativeSourceSpec", "RequestSpec"]

AttrKind = Literal["text", "html"] | str


class FieldSpec(BaseModel):
    """单个字段的取值规则。"""

    model_config = ConfigDict(extra="forbid")

    #: 相对当前元素的 CSS / XPath；留空表示元素自身
    selector: str = ""

    #: ``text`` / ``html`` / ``@属性名``
    attr: str = "text"

    regex: str | None = None
    regex_group: int | str = 1

    default: str | None = None

    #: 相对 URL 转绝对
    absolute: bool = False

    def extract(self, element: HtmlElement, base_url: str = "") -> str | None:
        """从元素中取出字段值。

        Raises:
            ValueError: 正则语法错误或分组不存在。
        """
        target: HtmlElement | None = element
        if self.selector:
            target = html_parser.select_one(element, self.selector)
        if target is None:
            return self.default

        value = self._read(target)
        if value is None:
            return self.default

        value = value.strip()
        if self.regex:
            extracted = text_parser.regex_extract(value, self.regex, self.regex_group, default=None)
            if extracted is None:
                return self.default
            value = extracted.strip()

        if self.absolute and base_url:
            value = urljoin(base_url, value)

        return value or self.default

    def _read(self, element: HtmlElement) -> str | None:
        """按 ``attr`` 取值。"""
        if self.attr == "text":
            return html_parser.element_to_text(element)
        if self.attr == "html":
            return html_parser.inner_html(element, "")
        if self.attr.startswith("@"):
            return element.get(self.attr[1:])
        # 未加 @ 前缀的按属性名处理，容错书源里的写法
        return element.get(self.attr)


class ListSpec(BaseModel):
    """列表型节点（搜索结果、目录）。"""

    model_config = ConfigDict(extra="forbid")

    #: 条目选择器
    selector: str

    #: 条目字段
    fields: dict[str, FieldSpec] = Field(default_factory=dict)

    def items(self, doc: HtmlElement, base_url: str = "") -> list[dict[str, str | None]]:
        """取出全部条目，每项是一个字段字典。"""
        rows: list[dict[str, str | None]] = []
        for element in html_parser.select(doc, self.selector):
            rows.append(
                {name: spec.extract(element, base_url) for name, spec in self.fields.items()}
            )
        return rows


class RequestSpec(BaseModel):
    """一次请求的定义。"""

    model_config = ConfigDict(extra="forbid")

    method: str = "GET"
    #: 相对书源根地址的路径，或完整 URL
    url: str
    params: dict[str, str] = Field(default_factory=dict)
    data: dict[str, str] = Field(default_factory=dict)
    headers: dict[str, str] = Field(default_factory=dict)

    def resolve_url(self, base_url: str) -> str:
        return urljoin(base_url, self.url)


class SearchSpec(RequestSpec):
    """搜索请求 + 结果解析。"""

    list: ListSpec


class BookInfoSpec(RequestSpec):
    """详情页请求 + 字段解析。"""

    fields: dict[str, FieldSpec] = Field(default_factory=dict)


class TocSpec(RequestSpec):
    """目录请求 + 条目解析。"""

    list: ListSpec
    #: 目录分页：下一页选择器（规划书 §22 要求有页数上限）
    next_page: str | None = None
    max_pages: int = Field(default=20, ge=1, le=200)


class ContentSpec(RequestSpec):
    """正文请求 + 清洗。"""

    #: 正文容器选择器
    selector: str
    #: 需要移除的节点（广告、导航、脚本）
    strip: list[str] = Field(default_factory=list)
    #: 正文分页：下一页选择器
    next_page: str | None = None
    max_pages: int = Field(default=20, ge=1, le=200)


class NativeSourceSpec(BaseModel):
    """一个完整的原生书源定义。"""

    model_config = ConfigDict(extra="forbid")

    name: str
    url: str

    #: 书源元信息
    version: str = "1.0"
    author: str | None = None
    license: str | None = None
    description: str | None = None

    #: 请求层默认值
    headers: dict[str, str] = Field(default_factory=dict)
    user_agent: str | None = None
    concurrency: int = Field(default=3, ge=1, le=32)
    requests_per_second: float = Field(default=2.0, gt=0)
    timeout: float = Field(default=20.0, gt=0)
    retry: int = Field(default=3, ge=0, le=10)

    search: SearchSpec | None = None
    book: BookInfoSpec | None = None
    toc: TocSpec | None = None
    content: ContentSpec | None = None

    def capability_report(self) -> dict[str, bool]:
        """声明了哪些能力。用于书源测试与 UI 展示。"""
        return {
            "search": self.search is not None,
            "book_info": self.book is not None,
            "toc": self.toc is not None,
            "content": self.content is not None,
        }

    @classmethod
    def from_raw(cls, raw: dict[str, Any]) -> NativeSourceSpec:
        """从字典构建。"""
        return cls.model_validate(raw)
