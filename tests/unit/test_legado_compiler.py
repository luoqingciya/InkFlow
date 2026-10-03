"""Legado 规则编译器测试。

覆盖 L0 + L1：选择器语法、模式前缀、正则替换、备选链、JS 识别。
"""

from __future__ import annotations

import pytest

from inkflow_legado.compiler import LegadoRuleCompiler, legado_selector_to_css
from inkflow_legado.rules import RuleContext, RuleMode
from inkflow_source.parsers import html as html_parser

pytestmark = pytest.mark.unit

HTML = """
<html><body>
  <div class="book-list">
    <div class="book-item odd">
      <h3><a href="/book/1">三体</a></h3>
      <span class="author">刘慈欣</span>
    </div>
    <div class="book-item">
      <h3><a href="/book/2">三体 II</a></h3>
      <span class="author">刘慈欣</span>
    </div>
  </div>
</body></html>
"""


@pytest.fixture
def compiler() -> LegadoRuleCompiler:
    return LegadoRuleCompiler()


@pytest.fixture
def context() -> RuleContext:
    return RuleContext(doc=html_parser.parse_html(HTML), base_url="https://example.com")


# ---------------------------------------------------------------- 选择器语法


@pytest.mark.parametrize(
    ("legado", "css"),
    [
        ("class.book-item", ".book-item"),
        ("tag.a", "a"),
        ("id.main", "#main"),
        ("class.a.b", ".a.b"),
        ("tag.div.highlight", "div.highlight"),
        (".already-css", ".already-css"),
        ("//div[@id='x']", "//div[@id='x']"),
    ],
)
def test_selector_translation(legado: str, css: str) -> None:
    assert legado_selector_to_css(legado) == css


def test_compiles_selector_chain_and_extract(compiler: LegadoRuleCompiler) -> None:
    """``class.x@tag.a@text`` → 逐级下钻 + 取文本。"""
    rule = compiler.compile("class.book-list@class.book-item@tag.a@text")
    assert rule.mode is RuleMode.CSS
    assert rule.selectors == [".book-list", ".book-item", "a"]
    assert rule.extract == "text"


def test_attribute_extract_is_absolutized(
    compiler: LegadoRuleCompiler, context: RuleContext
) -> None:
    """``@href`` 取到的相对地址要转成绝对地址。"""
    rule = compiler.compile("class.book-item@tag.a@href")
    assert rule.extract == "href"

    values = rule.evaluate(context)
    assert values == ["https://example.com/book/1", "https://example.com/book/2"]


def test_evaluates_text_values(compiler: LegadoRuleCompiler, context: RuleContext) -> None:
    rule = compiler.compile("class.book-item@tag.h3@tag.a@text")
    assert rule.evaluate(context) == ["三体", "三体 II"]


def test_arbitrary_attribute_name(compiler: LegadoRuleCompiler) -> None:
    """任意属性名应被识别为取值动作，而不是选择器。"""
    rule = compiler.compile("class.book-item@data-id")
    assert rule.extract == "data-id"
    assert rule.selectors == [".book-item"]


# ---------------------------------------------------------------- 模式前缀


def test_forced_css_prefix(compiler: LegadoRuleCompiler) -> None:
    rule = compiler.compile("@css:.book-item a@text")
    assert rule.mode is RuleMode.CSS
    assert rule.selectors == [".book-item a"]


def test_forced_xpath_prefix_with_attribute(
    compiler: LegadoRuleCompiler, context: RuleContext
) -> None:
    """``@XPath:`` 末尾的 ``/@href`` 应转成属性取值。

    注意 XPath 的 ``@class="x"`` 是**精确**匹配，节点上还有别的类名就匹配不上，
    因此实际书源里通常写 ``contains(@class,'x')``。
    """
    rule = compiler.compile("@XPath://div[contains(@class,'book-item')]//a/@href")
    assert rule.mode is RuleMode.XPATH
    assert rule.extract == "href"
    assert rule.selectors == ["//div[contains(@class,'book-item')]//a"]
    assert rule.evaluate(context) == ["https://example.com/book/1", "https://example.com/book/2"]


def test_forced_json_prefix(compiler: LegadoRuleCompiler) -> None:
    rule = compiler.compile("@json:$.data.list[*].name")
    assert rule.mode is RuleMode.JSON
    assert rule.json_path == "$.data.list[*].name"


def test_json_rule_evaluates() -> None:
    rule = LegadoRuleCompiler().compile("@json:$.items[*].name")
    context = RuleContext(data={"items": [{"name": "三体"}, {"name": "流浪地球"}]})
    assert rule.evaluate(context) == ["三体", "流浪地球"]


def test_js_rule_compiles_but_flags_js(compiler: LegadoRuleCompiler) -> None:
    """JS 规则编译成功但标记需要 L2 —— 执行时由适配器抛出明确错误。"""
    rule = compiler.compile("@js:result.replace(/x/g,'')")
    assert rule.mode is RuleMode.JS
    assert rule.needs_js is True


# ---------------------------------------------------------------- 替换与备选


def test_regex_replacement(compiler: LegadoRuleCompiler, context: RuleContext) -> None:
    """``##pattern##replacement`` 在取值后执行。"""
    rule = compiler.compile("class.book-item@tag.h3@tag.a@text##三体##ThreeBody")
    assert rule.evaluate(context) == ["ThreeBody", "ThreeBody II"]


def test_replacement_does_not_break_on_at_sign(compiler: LegadoRuleCompiler) -> None:
    """替换段里出现 ``@`` 不该影响选择器切分。"""
    rule = compiler.compile("class.book-item@tag.a@text##a@b##X")
    assert rule.selectors == [".book-item", "a"]
    assert rule.extract == "text"
    assert len(rule.replacements) == 1


def test_fallback_chain(compiler: LegadoRuleCompiler, context: RuleContext) -> None:
    """``||`` 备选：第一条无结果时用第二条。"""
    rule = compiler.compile("class.not-exist@tag.a@text||class.book-item@tag.h3@tag.a@text")
    assert rule.evaluate(context) == ["三体", "三体 II"]


# ---------------------------------------------------------------- 边界


def test_empty_rule_is_empty(compiler: LegadoRuleCompiler) -> None:
    assert compiler.compile("").is_empty
    assert compiler.compile(None).is_empty
    assert compiler.compile_optional("  ") is None


def test_invalid_regex_does_not_raise(compiler: LegadoRuleCompiler, context: RuleContext) -> None:
    """书源里的正则常写得不规范，替换失败不该让整章下载失败。"""
    rule = compiler.compile("class.book-item@tag.h3@tag.a@text##[unclosed##x")
    assert rule.evaluate(context) == ["三体", "三体 II"]


def test_describe_exposes_structure(compiler: LegadoRuleCompiler) -> None:
    """调试器需要结构化描述。"""
    described = compiler.compile("class.a@tag.b@href##x##y").describe()
    assert described["selectors"] == [".a", "b"]
    assert described["extract"] == "href"
    assert described["replacements"] == [{"pattern": "x", "replacement": "y"}]


# ---------------------------------------------------------------- 真实书源语法
#
# 下面这些写法都是从一份 1363 条的真实书源集合里统计出来的 ——
# 每一条都对应一个「不认就会报选择器语法错误」的缺口。


def test_implicit_jsonpath_without_prefix(compiler: LegadoRuleCompiler) -> None:
    """`$.xxx` 不写 `@json:` 也是 JSONPath。

    Legado 这么写很常见（样本里 1400+ 条），当 CSS 解析会直接语法错误。
    """
    rule = compiler.compile("$.result[*]")

    assert rule.mode is RuleMode.JSON
    assert rule.json_path == "$.result[*]"


def test_implicit_jsonpath_does_not_eat_css(compiler: LegadoRuleCompiler) -> None:
    """普通 CSS 选择器不受影响 —— 只有 `$` 开头才当 JSONPath。"""
    assert compiler.compile("class.book-item@tag.a").mode is RuleMode.CSS


def test_bang_index_suffix(compiler: LegadoRuleCompiler) -> None:
    """`!0` 取第 N 个（样本里 400+ 条）。

    下标留在选择器串里，由 `select_nodes` 在求值时拆 —— 这样 `Rule`
    不必为每个下标多存一个字段。
    """
    rule = compiler.compile("class.grid@tag.tr!0@text")

    assert rule.selectors == [".grid", "tr!0"]
    assert rule.extract == "text"


def test_dot_index_suffix(compiler: LegadoRuleCompiler) -> None:
    """`.0` 也是下标 —— CSS 类名不可能是纯数字，所以没有歧义。"""
    rule = compiler.compile(".book-metas.0@text")

    assert rule.selectors == [".book-metas.0"]
    assert rule.extract == "text"


def test_template_rule_is_text_mode(compiler: LegadoRuleCompiler) -> None:
    """`{{...}}` 是模板不是选择器。"""
    rule = compiler.compile("{{$.bookId}}")

    assert rule.mode is RuleMode.TEXT


def test_template_with_trailing_text(compiler: LegadoRuleCompiler) -> None:
    rule = compiler.compile("{{$.bookId}}&_sv=v2")

    assert rule.mode is RuleMode.TEXT


def _index_doc() -> object:
    from inkflow_source.parsers import html as html_parser

    return html_parser.parse_html(
        '<div class="grid"><tr><td>一</td></tr><tr><td>二</td></tr><tr><td>三</td></tr></div>'
    )


def test_bang_index_picks_nth(compiler: LegadoRuleCompiler) -> None:
    """`!N` 真的取到第 N 个 —— 只测「编译没报错」是不够的。"""
    context = RuleContext(doc=_index_doc())

    assert compiler.compile("class.grid@tag.tr!0@text").evaluate(context) == ["一"]
    assert compiler.compile("class.grid@tag.tr!2@text").evaluate(context) == ["三"]


def test_index_out_of_range_is_empty(compiler: LegadoRuleCompiler) -> None:
    """越界返回空列表，不抛异常 —— 书源写错下标不该让整章下载失败。"""
    context = RuleContext(doc=_index_doc())

    assert compiler.compile("class.grid@tag.tr!9@text").evaluate(context) == []


def test_negative_index_counts_from_end(compiler: LegadoRuleCompiler) -> None:
    """`.-1` 是倒数第一个（样本里出现过 `ul.-1@li`）。"""
    context = RuleContext(doc=_index_doc())

    assert compiler.compile("class.grid@tag.tr!-1@text").evaluate(context) == ["三"]


def test_index_range_slice(compiler: LegadoRuleCompiler) -> None:
    """`!0:2` 取前两个。"""
    context = RuleContext(doc=_index_doc())

    assert compiler.compile("class.grid@tag.tr!0:2@text").evaluate(context) == ["一", "二"]


def test_template_renders_json_path(compiler: LegadoRuleCompiler) -> None:
    """`{{$.xxx}}` 从当前 JSON 数据取值。"""
    rule = compiler.compile("{{$.bookId}}")
    context = RuleContext(data={"bookId": "12345"})

    assert rule.evaluate(context) == ["12345"]


def test_template_keeps_unknown_key(compiler: LegadoRuleCompiler) -> None:
    """变量不存在时保留原文 —— 便于定位书源里写错的变量名。"""
    rule = compiler.compile("{{$.missing}}")

    assert rule.evaluate(RuleContext(data={"bookId": "1"})) == ["{{$.missing}}"]


def test_template_with_literal_text(compiler: LegadoRuleCompiler) -> None:
    rule = compiler.compile("id={{$.bookId}}&v=2")

    assert rule.evaluate(RuleContext(data={"bookId": "9"})) == ["id=9&v=2"]


def test_unquoted_attr_selector_is_tolerated(compiler: LegadoRuleCompiler) -> None:
    """`meta[property=og:novel:author]` 这种没加引号的写法要能跑。

    书源里很常见，Legado（Jsoup）容忍；cssselect 严格，`:` 会被当伪类。
    """
    from inkflow_source.parsers import html as html_parser

    doc = html_parser.parse_html('<meta property="og:novel:author" content="刘慈欣" />')
    rule = compiler.compile("meta[property=og:novel:author]@content")

    assert rule.evaluate(RuleContext(doc=doc)) == ["刘慈欣"]
