"""正文清洗测试（规划书 §18）。"""

from __future__ import annotations

import pytest

from inkflow_source.normalizer import ContentNormalizer, NormalizeRules

pytestmark = pytest.mark.unit


@pytest.fixture
def normalizer() -> ContentNormalizer:
    return ContentNormalizer()


def test_strips_ad_lines(normalizer: ContentNormalizer) -> None:
    """推广行必须被剔除，正文保留。"""
    raw = "\n".join(
        [
            "请记住本站域名：mock.example.com",
            "汪淼觉得自己是在做梦。",
            "手机用户请访问 m.mock.example.com",
            "电话是丁仪打来的。",
            "一秒记住【mock.example.com】",
        ]
    )
    result = normalizer.clean_text(raw)

    assert "汪淼觉得自己是在做梦。" in result
    assert "电话是丁仪打来的。" in result
    assert "请记住本站" not in result
    assert "手机用户请访问" not in result
    assert "一秒记住" not in result


def test_does_not_strip_normal_sentence_starting_with_keyword(
    normalizer: ContentNormalizer,
) -> None:
    """广告模式必须锚定整行 —— 正文里出现「请记住」不该被误删。"""
    raw = "请记住，无论发生什么，都不要回头。"
    assert normalizer.clean_text(raw) == raw


def test_collapses_duplicate_paragraphs(normalizer: ContentNormalizer) -> None:
    """重复段落只保留一份。"""
    line = "汪淼觉得自己是在做梦。"
    raw = "\n".join([line, "他穿上了衣服。", line, "他走出了家门。", line])
    result = normalizer.clean_text(raw)

    assert result.count(line) == 1
    assert "他穿上了衣服。" in result


def test_keeps_short_repeated_lines(normalizer: ContentNormalizer) -> None:
    """短行的重复是正常表达，不该被去重。"""
    raw = "\n".join(["……", "……", "……", "好。"])
    assert normalizer.clean_text(raw).count("……") == 3


def test_collapses_blank_lines(normalizer: ContentNormalizer) -> None:
    raw = "第一段\n\n\n\n\n第二段"
    assert normalizer.clean_text(raw) == "第一段\n\n第二段"


def test_trims_noise_at_edges(normalizer: ContentNormalizer) -> None:
    raw = "\n".join(["------", "正文开始", "正文结束", "（未完待续）"])
    result = normalizer.clean_text(raw)
    assert result.startswith("正文开始")
    assert result.endswith("正文结束")


def test_normalize_html_removes_script_and_selector(normalizer: ContentNormalizer) -> None:
    """HTML 模式下应先按选择器移除节点，再抽文本。"""
    html = """
    <div id="content">
      <p>第一段</p>
      <script>console.log('x')</script>
      <div class="ad-inline">广告内容</div>
      <p>第二段</p>
    </div>
    """
    result = normalizer.normalize(html, is_html=True)

    assert "第一段" in result
    assert "第二段" in result
    assert "广告内容" not in result
    assert "console.log" not in result


def test_paragraph_breaks_preserved_from_br() -> None:
    """<br> 与块级标签必须产生换行，否则整章会挤成一行。"""
    html = "<div><p>第一段</p><p>第二段</p></div>"
    result = ContentNormalizer().normalize(html, is_html=True)
    assert result.split("\n") == ["第一段", "第二段"]


def test_custom_rules_are_additive() -> None:
    """自定义广告模式在默认模式之外追加生效。"""
    rules = NormalizeRules(ad_patterns=[r"^本站提示.*$"])
    result = ContentNormalizer(rules).clean_text("本站提示：测试\n正文内容")
    assert "本站提示" not in result
    assert "正文内容" in result


def test_empty_input_returns_empty(normalizer: ContentNormalizer) -> None:
    assert normalizer.normalize("") == ""
    assert normalizer.normalize("   \n  ") == ""
