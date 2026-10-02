"""原生书源端到端测试（对着 mock 站点跑完整流程）。

对应规划书 §77 的 MVP 验收流程：搜索 → 详情 → 目录 → 正文。
"""

from __future__ import annotations

import pytest

from inkflow_core.errors import SourceError
from inkflow_source.http import HttpClient
from tests.sources_data import NATIVE_SOURCE_TEMPLATE

pytestmark = pytest.mark.integration


@pytest.fixture
def adapter(state, mock_site: str):
    """导入并创建原生书源适配器。"""
    source = state.loader.load_text(NATIVE_SOURCE_TEMPLATE.format(base=mock_site))
    state.library.save_source(source)
    return state.registry.create(source)


# ---------------------------------------------------------------- 搜索


async def test_search_returns_all_books(adapter) -> None:
    results = await adapter.search("三体")

    assert len(results) == 3
    assert results[0].name == "三体"
    assert results[0].author == "刘慈欣"
    assert results[0].latest_chapter == "第三章 死神永生"


async def test_search_book_url_is_absolute(adapter) -> None:
    """相对地址必须转成绝对地址，否则后续请求无处可去。"""
    results = await adapter.search("三体")
    assert results[0].book_url.startswith("http://127.0.0.1:")


async def test_search_missing_capability_returns_empty(state, mock_site: str) -> None:
    """未声明 search 的书源返回空列表，而不是抛错。"""
    yaml_text = f"""
name: 只有目录的书源
url: {mock_site}
toc:
  url: /book/1/toc
  list:
    selector: "ul#chapter-list li a"
    fields:
      name: {{ selector: "", attr: text }}
      url: {{ selector: "", attr: "@href", absolute: true }}
"""
    source = state.loader.load_text(yaml_text)
    state.library.save_source(source)
    local_adapter = state.registry.create(source)

    assert await local_adapter.search("三体") == []


# ---------------------------------------------------------------- 详情


async def test_book_info_extracts_fields(adapter, mock_site: str) -> None:
    info = await adapter.book_info(f"{mock_site}/book/1")

    assert info.name == "三体"


async def test_book_info_applies_regex(adapter, mock_site: str) -> None:
    info = await adapter.book_info(f"{mock_site}/book/1")

    assert info.author == "刘慈欣"  # 正则去掉了「作者：」前缀
    assert info.cover_url.startswith("http://127.0.0.1:")  # 相对地址已绝对化
    assert info.latest_chapter == "第三章 死神永生"


async def test_book_info_parses_word_count(adapter, mock_site: str) -> None:
    """「23万字」要换算成 230000。"""
    info = await adapter.book_info(f"{mock_site}/book/1")
    assert info.word_count == 230000


# ---------------------------------------------------------------- 目录


async def test_chapters_follow_pagination(adapter, mock_site: str) -> None:
    """目录分页要自动翻页，且 index 连续。"""
    chapters = await adapter.chapters(f"{mock_site}/book/1")

    assert len(chapters) == 6  # 第一页 4 章 + 第二页 2 章
    assert [c.index for c in chapters] == list(range(6))
    assert chapters[0].name == "第一章 科学边界"
    assert chapters[5].name == "第六章 三体游戏"


async def test_chapters_urls_are_absolute_and_unique(adapter, mock_site: str) -> None:
    chapters = await adapter.chapters(f"{mock_site}/book/1")

    assert all(c.url.startswith("http://127.0.0.1:") for c in chapters)
    assert len({c.url for c in chapters}) == len(chapters)


# ---------------------------------------------------------------- 正文


async def test_content_extracts_and_cleans(adapter, mock_site: str) -> None:
    content = await adapter.content(f"{mock_site}/chapter/1")

    assert "汪淼觉得自己是在做梦。" in content.content
    assert "电话是丁仪打来的。" in content.content
    # 广告（DOM 节点 + 文本行两种形态）都应被清掉
    assert "请记住本站域名" not in content.content
    assert "手机用户请访问" not in content.content
    assert "一秒记住" not in content.content
    assert "console.log" not in content.content


async def test_content_keeps_raw_for_reprocessing(adapter, mock_site: str) -> None:
    """raw 必须保留 —— 改清洗规则时不该重新抓取。"""
    content = await adapter.content(f"{mock_site}/chapter/1")

    assert content.raw
    # 噪声在原始数据里还在，只是清洗后才消失
    assert "console.log" in content.raw
    assert "console.log" not in content.content
    assert content.raw != content.content


# ---------------------------------------------------------------- 安全


async def test_private_network_blocked_by_default(mock_site: str) -> None:
    """默认禁止访问内网 —— 书源是不可信输入。"""
    from inkflow_core.models import (
        BookSource,
        RequestConfig,
        SourceFormat,
        SourceType,
    )
    from inkflow_source.native.schema import NativeSourceSpec
    from inkflow_source.registration import native_factory

    source = BookSource(
        id="src_ssrf",
        name="SSRF 测试",
        url=mock_site,
        source_type=SourceType.NATIVE,
        source_format=SourceFormat.NATIVE_YAML,
        request=RequestConfig(),
        raw={
            "name": "SSRF 测试",
            "url": mock_site,
            "search": {
                "url": "/search",
                "list": {"selector": "div.book-item", "fields": {}},
            },
        },
    )
    # 不传 http，让适配器按默认配置创建（allow_private_network=False）
    local_adapter = native_factory(source, None)

    with pytest.raises(SourceError) as excinfo:
        await local_adapter.search("三体")

    assert excinfo.value.code == "SOURCE_BLOCKED"
    _ = NativeSourceSpec  # 保持导入用于类型检查路径


async def test_http_client_rejects_non_http_scheme() -> None:
    client = HttpClient(allow_private_network=True)
    try:
        with pytest.raises(SourceError) as excinfo:
            await client.get("file:///etc/passwd")
        assert excinfo.value.code == "SOURCE_BLOCKED"
    finally:
        await client.aclose()
