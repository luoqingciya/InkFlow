"""统一规则 AST。

**设计要点（规划书 §5）**：Legado 的规则 DSL 不直接执行，而是先编译成这里的
``Rule`` 对象。业务代码因此永远不会出现 ``if legado_xxx: ...`` 这种分支 ——
执行器只认识 AST。

    Legado DSL  →  统一 AST  →  执行器
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any
from urllib.parse import urljoin

from lxml.html import HtmlElement

from inkflow_source.parsers import html as html_parser
from inkflow_source.parsers import json as json_parser

__all__ = ["Replacement", "Rule", "RuleContext", "RuleMode"]


class RuleMode(StrEnum):
    """规则的取值方式。"""

    CSS = "css"
    XPATH = "xpath"
    JSON = "json"
    TEXT = "text"
    """不对 DOM 求值，直接对已有文本做正则/替换。"""

    JS = "js"
    """需要 JS 运行时（L2）。MVP 阶段编译成功但执行时抛错。"""


@dataclass(slots=True)
class Replacement:
    """``##pattern##replacement`` 形式的正则替换。"""

    pattern: str
    replacement: str

    def apply(self, value: str) -> str:
        try:
            return re.sub(self.pattern, self.replacement, value)
        except re.error:
            # 书源里的正则经常写得不规范；替换失败不应该让整章下载失败
            return value


@dataclass(slots=True)
class RuleContext:
    """规则求值上下文。"""

    doc: HtmlElement | None = None
    data: Any = None
    base_url: str = ""

    @property
    def is_json(self) -> bool:
        return self.data is not None and self.doc is None


@dataclass(slots=True)
class Rule:
    """一条已编译的规则。

    Attributes:
        raw: 原始规则字符串，保留用于调试器展示。
        mode: 取值方式。
        selectors: 选择器链，逐级下钻（``.a@b`` 表示先取 ``.a`` 再在其内取 ``b``）。
        json_path: JSON 模式下的 JSONPath 表达式。
        extract: 取值动作：``text`` / ``html`` / ``href`` / 任意属性名。
        replacements: 取值后依次执行的正则替换。
        fallbacks: ``||`` 的备选规则，前一条无结果时依次尝试。
    """

    raw: str
    mode: RuleMode = RuleMode.CSS
    selectors: list[str] = field(default_factory=list)
    json_path: str | None = None
    extract: str = "text"
    replacements: list[Replacement] = field(default_factory=list)
    fallbacks: list[Rule] = field(default_factory=list)

    # -- 判断 --------------------------------------------------------------

    @property
    def is_empty(self) -> bool:
        """规则是否为空（未配置）。

        判定依据是**原始规则串是否为空**，而不是选择器是否为空：
        ``chapterName: "text"`` / ``chapterUrl: "href"`` 这类规则没有选择器，
        但含义是「作用于当前元素自身」，是完全有效的规则 ——
        按选择器判空会把它们全部丢掉，目录就永远是空的。
        """
        return not self.raw.strip()

    @property
    def needs_js(self) -> bool:
        return self.mode is RuleMode.JS

    # -- 求值 --------------------------------------------------------------

    def select_nodes(self, doc: HtmlElement) -> list[HtmlElement]:
        """按选择器链取出元素列表（不做取值）。

        用于 ``bookList`` / ``chapterList`` 这类需要元素集合的规则。
        """
        if not self.selectors:
            return [doc]
        nodes: list[HtmlElement] = [doc]
        for selector in self.selectors:
            next_nodes: list[HtmlElement] = []
            for node in nodes:
                next_nodes.extend(html_parser.select(node, selector))
            nodes = next_nodes
            if not nodes:
                return []
        return nodes

    def evaluate(self, context: RuleContext) -> list[str]:
        """求值，返回全部结果（已去空、已替换、URL 已绝对化）。"""
        results = self._evaluate_self(context)
        if results:
            return results
        for fallback in self.fallbacks:
            results = fallback._evaluate_self(context)
            if results:
                return results
        return []

    def evaluate_one(self, context: RuleContext) -> str | None:
        """求值并返回第一个结果。"""
        results = self.evaluate(context)
        return results[0] if results else None

    def _evaluate_self(self, context: RuleContext) -> list[str]:
        """不含备选链的求值。"""
        if self.mode is RuleMode.JSON:
            return self._evaluate_json(context)
        if context.doc is None:
            return []
        return self._evaluate_html(context)

    def _evaluate_html(self, context: RuleContext) -> list[str]:
        doc = context.doc
        assert doc is not None
        values: list[str] = []
        for node in self.select_nodes(doc):
            value = self._extract(node, context.base_url)
            if value:
                values.append(self._apply_replacements(value))
        return values

    def _evaluate_json(self, context: RuleContext) -> list[str]:
        if self.json_path is None:
            return []
        try:
            raw_values = json_parser.query(context.data, self.json_path)
        except ValueError:
            return []
        values: list[str] = []
        for item in raw_values:
            text = json_parser.as_text(item)
            if text:
                values.append(self._apply_replacements(text))
        return values

    def _extract(self, element: HtmlElement, base_url: str) -> str | None:
        """从元素中取值。"""
        action = self.extract or "text"

        if action in ("text", "textNodes"):
            text = element.text_content()
            return " ".join(text.split()) if text else None
        if action == "ownText":
            text = element.text or ""
            return " ".join(text.split()) if text else None
        if action in ("html", "all", "outerHtml"):
            return html_parser.outer_html(element)
        if action == "innerHtml":
            return html_parser.inner_html(element, "")

        value = element.get(action)
        if value is None:
            return None
        if action in ("href", "src", "data-src", "data-original"):
            return urljoin(base_url, value) if base_url else value
        return value

    def _apply_replacements(self, value: str) -> str:
        for replacement in self.replacements:
            value = replacement.apply(value)
        return value.strip()

    # -- 调试 --------------------------------------------------------------

    def describe(self) -> dict[str, Any]:
        """规则的结构化描述，供 Source Debugger 展示（规划书 §43）。"""
        return {
            "raw": self.raw,
            "mode": str(self.mode),
            "selectors": list(self.selectors),
            "json_path": self.json_path,
            "extract": self.extract,
            "replacements": [
                {"pattern": r.pattern, "replacement": r.replacement} for r in self.replacements
            ],
            "fallbacks": [f.raw for f in self.fallbacks],
        }
