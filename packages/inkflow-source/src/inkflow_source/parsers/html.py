"""HTML 解析原语（CSS Selector / XPath）。

这些是 Legado 规则编译后的**执行目标**：规则先被编译成
「选择器 + 取值方式」的调用，再由这里执行。业务代码不会直接调用它们。
"""

from __future__ import annotations

from typing import Any

from lxml import etree
from lxml import html as lxml_html
from lxml.html import HtmlElement

__all__ = [
    "attr_of",
    "attrs_of",
    "inner_html",
    "outer_html",
    "parse_html",
    "select",
    "select_one",
    "text_of",
    "texts_of",
]


def parse_html(source: str | bytes, *, base_url: str | None = None) -> HtmlElement:
    """把 HTML 文本解析为可查询的 DOM。

    使用 lxml 的容错解析器 —— 小说站点大量存在未闭合标签，
    严格解析会直接抛错。
    """
    if isinstance(source, str):
        source = source.encode("utf-8", errors="replace")
    parser = lxml_html.HTMLParser(recover=True, encoding="utf-8")
    doc = lxml_html.fromstring(source, parser=parser, base_url=base_url)
    return doc


def _apply(doc: HtmlElement, selector: str) -> list[HtmlElement]:
    """按选择器取元素。``/`` 开头视为 XPath，否则视为 CSS。"""
    selector = selector.strip()
    if not selector:
        return []
    if selector.startswith(("/", "(")):
        result = doc.xpath(selector)
        return [node for node in result if isinstance(node, etree._Element)]
    return list(doc.cssselect(selector))


def select(doc: HtmlElement | str, selector: str) -> list[HtmlElement]:
    """按选择器取全部匹配元素。"""
    if isinstance(doc, str):
        doc = parse_html(doc)
    return _apply(doc, selector)


def select_one(doc: HtmlElement | str, selector: str) -> HtmlElement | None:
    """取第一个匹配元素，无匹配返回 ``None``。"""
    matches = select(doc, selector)
    return matches[0] if matches else None


def text_of(doc: HtmlElement | str, selector: str, *, default: str | None = None) -> str | None:
    """取第一个匹配元素的**纯文本**（已折叠空白）。"""
    element = select_one(doc, selector)
    if element is None:
        return default
    text = element.text_content()
    return " ".join(text.split()) if text else default


def texts_of(doc: HtmlElement | str, selector: str) -> list[str]:
    """取全部匹配元素的纯文本。"""
    return [" ".join(el.text_content().split()) for el in select(doc, selector)]


def attr_of(
    doc: HtmlElement | str,
    selector: str,
    attr: str,
    *,
    default: str | None = None,
) -> str | None:
    """取第一个匹配元素的属性值。"""
    element = select_one(doc, selector)
    if element is None:
        return default
    value = element.get(attr)
    return value if value is not None else default


def attrs_of(doc: HtmlElement | str, selector: str, attr: str) -> list[str]:
    """取全部匹配元素的同名属性值，缺失的跳过。"""
    values: list[str] = []
    for element in select(doc, selector):
        value = element.get(attr)
        if value is not None:
            values.append(value)
    return values


def inner_html(doc: HtmlElement | str, selector: str) -> str | None:
    """取元素的内部 HTML。"""
    element = select_one(doc, selector)
    if element is None:
        return None
    return "".join(
        [element.text or ""] + [etree.tostring(child, encoding="unicode") for child in element]
    )


def outer_html(element: HtmlElement) -> str:
    """取元素自身的 HTML。"""
    return etree.tostring(element, encoding="unicode")


def drop_elements(doc: HtmlElement, selector: str) -> int:
    """删除匹配的元素，返回删除数量。

    正文清洗中「移除广告节点」依赖此函数（规划书 §18）。
    """
    removed = 0
    for element in _apply(doc, selector):
        parent = element.getparent()
        if parent is not None:
            parent.remove(element)
            removed += 1
    return removed


def element_to_text(element: HtmlElement) -> str:
    """把 DOM 转成保留段落结构的纯文本。

    ``text_content()`` 会把 ``<br>`` 和 ``<p>`` 的换行全部吃掉，
    导致整章正文挤成一行 —— 因此这里显式补换行。
    """
    for br in element.xpath(".//br"):
        br.tail = "\n" + (br.tail or "")
    block_tags = ("p", "div", "h1", "h2", "h3", "h4", "li", "tr", "section", "article")
    for block in element.xpath("|".join(f".//{tag}" for tag in block_tags)):
        block.tail = "\n" + (block.tail or "")
    return element.text_content()


def to_text(source: str | HtmlElement) -> str:
    """HTML → 纯文本的便捷入口。"""
    doc = parse_html(source) if isinstance(source, str) else source
    return element_to_text(doc)


def as_dict(element: HtmlElement) -> dict[str, Any]:
    """元素的基本信息，调试器展示用（规划书 §43）。"""
    return {
        "tag": element.tag,
        "text": " ".join((element.text_content() or "").split())[:200],
        "attrs": dict(element.attrib),
    }
