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
from inkflow_source.parsers import text as text_parser

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
    #: 模板规则（``{{...}}``）用的变量表。普通选择器规则用不到。
    variables: dict[str, Any] = field(default_factory=dict)

    @property
    def is_json(self) -> bool:
        return self.data is not None and self.doc is None


#: 模板里的 ``{{...}}`` 占位符
_TEMPLATE_KEY_RE = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}")

#: Legado 的下标后缀，真实书源里见过三种写法：
#:   ``!0`` / ``!0:2`` —— 感叹号形式
#:   ``.0``            —— 点号形式（CSS 类名不可能是纯数字，所以没有歧义）
#:   ``.-1``           —— 负数表示倒数（``-1`` 是最后一个）
_BANG_INDEX_RE = re.compile(r"^(?P<base>.*?)!(?P<start>-?\d+)(?::(?P<stop>-?\d+))?$")
_DOT_INDEX_RE = re.compile(r"^(?P<base>.+)\.(?P<start>-?\d+)$")

#: 属性选择器的值没加引号：``[property=og:novel:author]``。
#: 书源里这么写很常见，Legado（Jsoup）容忍，但 cssselect 会把 ``:`` 当伪类、
#: 把 ``|`` 当命名空间分隔符而报错。补上引号即可。
_UNQUOTED_ATTR_RE = re.compile(r"""\[(?P<name>[\w-]+)(?P<op>[~^$*|]?=)(?P<value>[^"'\]\s]+)\]""")


def _quote_attr_values(selector: str) -> str:
    """给属性选择器的裸值补引号。

    ``meta[property=og:novel:author]`` → ``meta[property="og:novel:author"]``

    只处理「值里含 ``:`` 或 ``|``」的情况 —— 普通的 ``[href=/x]`` 不动，
    避免给本来就正常的规则引入变化。
    """
    if "[" not in selector:
        return selector

    def _sub(match: re.Match[str]) -> str:
        value = match.group("value")
        if ":" not in value and "|" not in value:
            return match.group(0)
        return f'[{match.group("name")}{match.group("op")}"{value}"]'

    return _UNQUOTED_ATTR_RE.sub(_sub, selector)


def _split_index_suffix(selector: str) -> tuple[str, tuple[int, int | None] | None]:
    """把 ``tag.tr!0`` / ``.book-metas.0`` 拆成 ``(选择器, (起点, 终点))``。

    下标只认**末尾**的标记 —— 选择器本身不会以 ``!`` 或 ``.数字`` 结尾。
    """
    match = _BANG_INDEX_RE.match(selector)
    if match is not None:
        start = int(match.group("start"))
        stop_text = match.group("stop")
        return match.group("base"), (start, int(stop_text) if stop_text else None)

    match = _DOT_INDEX_RE.match(selector)
    if match is not None:
        return match.group("base"), (int(match.group("start")), None)

    return selector, None


def _apply_index(nodes: list[HtmlElement], index: tuple[int, int | None]) -> list[HtmlElement]:
    """按下标取元素。

    - 非负：``!0`` 取第 0 个
    - 负数：``.-1`` 取倒数第一个
    - 越界：返回空列表（不是异常）

    单点取值用切片而不是 ``nodes[i]``，这样越界自然是空列表，
    不必额外判长度。
    """
    start, stop = index
    if stop is None:
        if start < 0:
            return nodes[start:] if -start <= len(nodes) else []
        return nodes[start : start + 1]
    return nodes[start:stop]


@dataclass(slots=True)
class Rule:
    """一条已编译的规则。    Attributes:
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
    #: JS 模式下的代码（已剥离 ``@js:`` 前缀）。单独存是因为 ``raw`` 含前缀，
    #: 直接丢给 JS 引擎会语法错误。
    code: str | None = None
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

        支持 Legado 的 ``!N`` 下标后缀（可出现在链的任意一级）：
        ``class.grid@tag.tr!0`` 表示「取 ``tag.tr`` 的第 0 个」。
        真实书源里这个写法有 400 多条，不认就会报选择器语法错误。
        """
        if not self.selectors:
            return [doc]
        # TEXT 模式的「选择器」其实是模板字符串，不是 CSS ——
        # 拿去解析必然语法错误。JSON 模式同理（走的是 json_path）。
        if self.mode in (RuleMode.TEXT, RuleMode.JSON):
            return [doc]
        nodes: list[HtmlElement] = [doc]
        for selector in self.selectors:
            base, index = _split_index_suffix(selector)
            next_nodes: list[HtmlElement] = []
            for node in nodes:
                found = html_parser.select(node, _quote_attr_values(base)) if base else [node]
                if index is not None:
                    found = _apply_index(found, index)
                next_nodes.extend(found)
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
        if self.mode is RuleMode.TEXT:
            return self._evaluate_text(context)
        if context.doc is None:
            return []
        return self._evaluate_html(context)

    def _evaluate_text(self, context: RuleContext) -> list[str]:
        """TEXT 模式：渲染 ``{{...}}`` 模板，不走 DOM。

        模板里的表达式按 Legado 语义在当前上下文求值：
        ``{{$.xxx}}`` 从当前 JSON 数据取 JSONPath，其余按变量名查表。
        """
        if not self.selectors:
            return []
        template = self.selectors[0]

        variables = dict(context.variables)
        if context.data is not None:
            for key in _TEMPLATE_KEY_RE.findall(template):
                if not key.startswith("$"):
                    continue
                try:
                    values = json_parser.query(context.data, key)
                except ValueError:
                    values = []
                if values:
                    variables[key] = json_parser.as_text(values[0])

        # 先做**精确**替换：`{{$.bookId}}` 里的 `$.bookId` 是一个整体键，
        # 交给 render_template 会被按 `.` 拆成嵌套路径而找不到。
        # 剩下的（如 `{{page}}`）再走通用渲染。
        rendered = _TEMPLATE_KEY_RE.sub(
            lambda m: str(variables[m.group(1)]) if m.group(1) in variables else m.group(0),
            template,
        )
        if "{{" in rendered:
            rendered = text_parser.render_template(rendered, variables)

        return [self._apply_replacements(rendered)] if rendered else []

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
