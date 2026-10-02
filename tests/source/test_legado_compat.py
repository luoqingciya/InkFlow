"""Legado 书源兼容性测试（规划书 §44）。

对着 mock 站点跑真实的 Legado JSON 书源，验证 L0 + L1 的解析与执行链路。
"""

from __future__ import annotations

import pytest

from inkflow_core.models import CompatibilityLevel, SourceType
from inkflow_legado import LegadoBookSource, LegadoSourceAdapter, build_legado_source
from tests.sources_data import legado_source

pytestmark = pytest.mark.source


@pytest.fixture
def source_def(mock_site: str) -> dict:
    return legado_source(mock_site)


@pytest.fixture
def adapter(state, source_def: dict, mock_site: str):
    """导入 Legado 书源并创建适配器。"""
    source = state.loader.load_text(__import__("json").dumps(source_def, ensure_ascii=False))
    state.library.save_source(source)
    return state.registry.create(source)


# ---------------------------------------------------------------- L0：结构


def test_l0_parses_structure(source_def: dict) -> None:
    definition = LegadoBookSource.model_validate(source_def)
    assert definition.bookSourceName == "Mock Legado 书源"
    assert definition.search_enabled is True
    assert definition.uses_js() is False
    assert definition.needs_browser() is False


def test_l0_unknown_fields_are_preserved() -> None:
    """书源生态有大量自定义字段，严格校验会让用户导不进来。"""
    definition = LegadoBookSource.model_validate(
        {
            "bookSourceName": "X",
            "bookSourceUrl": "https://x.test",
            "someVendorExtension": {"a": 1},
        }
    )
    assert definition.model_extra is not None
    assert definition.model_extra["someVendorExtension"] == {"a": 1}


def test_l0_tolerates_broken_header_json() -> None:
    """header 字段经常是半截 JSON，解析失败应退化为空而不是导入失败。"""
    definition = LegadoBookSource.model_validate(
        {"bookSourceName": "X", "bookSourceUrl": "https://x.test", "header": "{broken"}
    )
    assert definition.headers == {}


def test_level_detection_is_l1(source_def: dict) -> None:
    source = build_legado_source(source_def)
    assert source.source_type is SourceType.LEGADO
    assert source.compatibility_level is CompatibilityLevel.L1


def test_level_detection_marks_js_sources_as_l2() -> None:
    source = build_legado_source(
        {
            "bookSourceName": "JS 书源",
            "bookSourceUrl": "https://x.test",
            "ruleSearch": {"name": "@js:result.replace(/x/,'')"},
        }
    )
    assert source.compatibility_level is CompatibilityLevel.L2


def test_stable_source_id_is_deterministic(source_def: dict) -> None:
    """同一书源重复导入得到同一 ID，导入因此是幂等的。"""
    first = build_legado_source(source_def)
    second = build_legado_source(source_def)
    assert first.id == second.id


# ---------------------------------------------------------------- L1：执行


async def test_l1_search(adapter: LegadoSourceAdapter) -> None:
    results = await adapter.search("三体")

    assert len(results) == 3
    assert results[0].name == "三体"
    assert results[0].author == "刘慈欣"
    assert results[0].category == "科幻"
    assert results[0].book_url.startswith("http://127.0.0.1:")


async def test_l1_book_info_with_regex_replacement(
    adapter: LegadoSourceAdapter, mock_site: str
) -> None:
    """``##作者：##`` 应把前缀替换掉。"""
    info = await adapter.book_info(f"{mock_site}/book/1")

    assert info.name == "三体"
    assert info.author == "刘慈欣"
    assert info.category == "科幻"
    assert info.latest_chapter == "第三章 死神永生"
    assert info.cover_url is not None
    assert info.cover_url.startswith("http://127.0.0.1:")


async def test_l1_toc_with_element_self_rules(adapter: LegadoSourceAdapter, mock_site: str) -> None:
    """``chapterName: "text"`` / ``chapterUrl: "href"`` 作用于条目元素自身。"""
    chapters = await adapter.chapters(f"{mock_site}/book/1")

    assert len(chapters) == 6
    assert chapters[0].name == "第一章 科学边界"
    assert chapters[0].url.endswith("/chapter/1")
    assert [c.index for c in chapters] == list(range(6))


async def test_l1_content_is_cleaned(adapter: LegadoSourceAdapter, mock_site: str) -> None:
    content = await adapter.content(f"{mock_site}/chapter/1")

    assert "汪淼觉得自己是在做梦。" in content.content
    assert "请记住本站域名" not in content.content
    assert "console.log" not in content.content


# ---------------------------------------------------------------- 等级边界


async def test_l2_js_rule_fails_loudly(state, mock_site: str) -> None:
    """JS 规则必须抛出明确错误，不能静默返回空结果。"""
    from inkflow_core.errors import SourceError

    js_source = legado_source(mock_site)
    js_source["ruleContent"]["content"] = "@js:result.replace(/广告/g,'')"

    source = state.loader.load_text(__import__("json").dumps(js_source, ensure_ascii=False))
    state.library.save_source(source)
    js_adapter = state.registry.create(source)

    with pytest.raises(SourceError) as excinfo:
        await js_adapter.content(f"{mock_site}/chapter/1")

    assert excinfo.value.code == "SOURCE_EXECUTION_ERROR"
    assert "L2" in excinfo.value.message


async def test_empty_content_rule_raises(state, mock_site: str) -> None:
    """规则匹配不到正文时要说清楚，而不是返回空字符串。"""
    from inkflow_core.errors import SourceError

    broken = legado_source(mock_site)
    broken["ruleContent"]["content"] = "id.not-exist@text"

    source = state.loader.load_text(__import__("json").dumps(broken, ensure_ascii=False))
    state.library.save_source(source)
    broken_adapter = state.registry.create(source)

    with pytest.raises(SourceError) as excinfo:
        await broken_adapter.content(f"{mock_site}/chapter/1")

    assert excinfo.value.code == "CONTENT_PARSE_FAILED"


def test_rules_endpoint_exposes_ast(client, mock_site: str) -> None:
    """Source Debugger 应能看到编译后的规则结构（规划书 §43）。"""
    import json

    source_id = client.post(
        "/api/v1/sources/import",
        json={"content": json.dumps(legado_source(mock_site), ensure_ascii=False)},
    ).json()["source"]["id"]

    body = client.get(f"/api/v1/sources/{source_id}/rules").json()

    assert body["compatibility_level"] == "L1"
    assert body["uses_js"] is False
    assert body["rules"]["search.bookList"]["selectors"] == [".book-item"]
    assert body["rules"]["toc.chapterName"]["extract"] == "text"
    assert body["rules"]["toc.chapterName"]["selectors"] == []
