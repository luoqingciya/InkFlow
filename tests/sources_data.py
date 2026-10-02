"""测试用书源定义。

集中放在这里，让 API 测试与书源兼容性测试使用**同一份**定义 ——
否则两处会各自漂移，测出来的东西就不是一回事了。
"""

from __future__ import annotations

from typing import Any

__all__ = ["NATIVE_SOURCE_TEMPLATE", "LEGADO_SOURCE_TEMPLATE", "legado_source"]

#: 原生书源（Level 1）。``{base}`` 由 mock 站点的地址填充。
NATIVE_SOURCE_TEMPLATE = """
name: Mock 原生书源
url: {base}
description: 用于集成测试的原生书源
search:
  url: /search
  params:
    q: "{{{{key}}}}"
  list:
    selector: div.book-item
    fields:
      name: {{ selector: "h3 a", attr: text }}
      author: {{ selector: ".author", attr: text }}
      book_url: {{ selector: "h3 a", attr: "@href", absolute: true }}
      latest_chapter: {{ selector: ".latest", attr: text }}
book:
  url: /book/1
  fields:
    name: {{ selector: "h1.book-name", attr: text }}
    # 正则用单引号：YAML 双引号串里 \\S 是非法转义，会直接解析失败
    author: {{ selector: ".author", attr: text, regex: '作者：(\\S+)' }}
    intro: {{ selector: "#intro", attr: text }}
    cover_url: {{ selector: "#cover", attr: "@src", absolute: true }}
    word_count: {{ selector: ".word-count", attr: text }}
    # 用 (.+) 而不是非空白匹配：章节名里有空格，后者会截断
    latest_chapter: {{ selector: ".latest", attr: text, regex: '最新章节：(.+)' }}
toc:
  url: /book/1/toc
  next_page: "a.next-page"
  list:
    selector: "ul#chapter-list li a"
    fields:
      name: {{ selector: "", attr: text }}
      url: {{ selector: "", attr: "@href", absolute: true }}
content:
  url: /chapter/1
  selector: "div#content"
  strip: ["div.ad-inline"]
"""


def legado_source(base: str) -> dict[str, Any]:
    """Legado JSON 书源，规则刻意用多种写法覆盖编译器分支。

    * ``class.x`` / ``tag.a`` 的 Legado 选择器语法
    * ``##`` 正则替换（去掉「作者：」前缀）
    * ``chapterName: "text"`` 这种「作用于元素自身」的写法
    """
    return {
        "bookSourceName": "Mock Legado 书源",
        "bookSourceUrl": base,
        "bookSourceGroup": "测试",
        "bookSourceComment": "仅用于测试",
        "enabled": True,
        "searchUrl": "/search?q={{key}}",
        "ruleSearch": {
            "bookList": "class.book-item",
            "name": "tag.h3@tag.a@text",
            "author": "class.author@text",
            "kind": "class.kind@text",
            "lastChapter": "class.latest@text",
            "bookUrl": "tag.h3@tag.a@href",
        },
        "ruleBookInfo": {
            "name": "class.book-name@text",
            "author": "class.author@text##作者：##",
            "kind": "class.kind@text##分类：##",
            "intro": "id.intro@text",
            "coverUrl": "id.cover@src",
            "lastChapter": "class.latest@text##最新章节：##",
            # 目录页地址从详情页取；不配的话适配器会去详情页找目录
            "tocUrl": "class.toc-link@href",
        },
        "ruleToc": {
            "chapterList": "id.chapter-list@tag.li@tag.a",
            "chapterName": "text",
            "chapterUrl": "href",
            "nextTocUrl": "class.next-page@href",
        },
        "ruleContent": {
            "content": "id.content@html",
        },
    }


#: 与 ``legado_source`` 等价但用 ``@css:`` / ``@XPath:`` 前缀的变体
LEGADO_SOURCE_TEMPLATE = legado_source
