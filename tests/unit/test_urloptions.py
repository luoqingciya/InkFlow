"""``url,{options}`` 解析测试。

重点在**宽松**：真实书源写的是 Gson 风格（单引号、小写布尔），标准 ``json``
读不了 —— 读不了的后果是整段选项被当成 URL 的一部分，请求打到一个不存在的
地址上。
"""

from __future__ import annotations

import pytest

from inkflow_legado.urloptions import parse_options, split_url_options

pytestmark = pytest.mark.unit


# ================================================================ 拆分


def test_plain_url_is_untouched() -> None:
    assert split_url_options("https://x.test/a") == ("https://x.test/a", {})


def test_url_without_braces_is_untouched() -> None:
    """逗号后面不是对象时不能乱切 —— URL 里本来就可能带逗号。"""
    text = "https://x.test/a?q=1,2"
    assert split_url_options(text) == (text, {})


def test_json_options_are_split() -> None:
    url, options = split_url_options('https://x.test/s,{"method":"POST","body":"k=1"}')

    assert url == "https://x.test/s"
    assert options == {"method": "POST", "body": "k=1"}


def test_single_quoted_options_are_split() -> None:
    """真实书源的主流写法 —— 标准 json 读不了，得靠宽松解析。"""
    url, options = split_url_options("https://x.test/a,{'webView': true}")

    assert url == "https://x.test/a"
    assert options == {"webView": True}


def test_options_after_regex_replacement() -> None:
    """``a@href##$##,{'webView': true}`` —— 替换后的结果就是这个形状。"""
    url, options = split_url_options("https://x.test/c1,{'webView': true}")

    assert url == "https://x.test/c1"
    assert options["webView"] is True


def test_broken_options_keep_original_text() -> None:
    """解析不了时返回原文 —— 宁可不识别，也不要猜错 URL。"""
    text = "https://x.test/a,{'webView': "
    assert split_url_options(text) == (text, {})


# ================================================================ 宽松解析


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("{'a': 1}", {"a": 1}),
        ('{"a": 1}', {"a": 1}),
        ("{a: 1}", {"a": 1}),  # 键不带引号
        ("{'a': true, 'b': false, 'c': null}", {"a": True, "b": False, "c": None}),
        ("{'a': 'x'}", {"a": "x"}),
        ("{'a': 1.5}", {"a": 1.5}),
        ("{'a': [1, 2]}", {"a": [1, 2]}),
        ("{'a': {'b': 'c'}}", {"a": {"b": "c"}}),
        # 值里的引号不能把解析带偏
        ("{'body': \"s=true&x=1\", 'method': 'POST'}", {"body": "s=true&x=1", "method": "POST"}),
    ],
)
def test_lenient_parsing(text: str, expected: dict) -> None:
    assert parse_options(text) == expected


def test_nested_headers_survive() -> None:
    """``headers`` 是嵌套对象，宽松解析也得撑住。"""
    options = parse_options("{'headers': {'Referer': 'https://x.test'}, 'webView': true}")

    assert options == {"headers": {"Referer": "https://x.test"}, "webView": True}


def test_non_object_returns_none() -> None:
    """选项必须是对象；是数组或标量时当作没选项。"""
    assert parse_options("[1, 2]") is None
    assert parse_options("'text'") is None


def test_garbage_returns_none() -> None:
    assert parse_options("{不是 JSON}") is None
