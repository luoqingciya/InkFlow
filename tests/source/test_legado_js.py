"""Legado L2（``@js:`` 规则）端到端测试。

跑的是**真的 Node sidecar**：书源规则里写 ``@js:``，经过适配器 →
JS 运行时 → 沙箱执行 → 结果回到解析流程。

这里特意不用 mock 顶掉运行时 —— 要验证的正是「这条链路通不通」。
"""

from __future__ import annotations

import json

import pytest
from inkflow_js_runtime import JsRuntime, find_node

from inkflow_core.config import Settings
from inkflow_core.errors import SourceError
from inkflow_legado import LegadoBookSource, LegadoSourceAdapter
from inkflow_legado.rules import RuleContext
from tests.sources_data import legado_source

pytestmark = pytest.mark.source

requires_node = pytest.mark.skipif(find_node() is None, reason="机器上没有 Node.js")


@pytest.fixture
def source_with_js(mock_site: str) -> dict:
    """把书名规则换成 ``@js:`` —— 其余保持标准书源不变。"""
    definition = legado_source(mock_site)
    definition["ruleBookInfo"]["name"] = "@js:'JS 算出来的书名'"
    return definition


@pytest.fixture
async def js_state(tmp_path, mock_site: str):
    """启用了 JS 运行时的应用状态。

    用完要 shutdown —— 否则 sidecar 子进程会留着，pytest 报
    ``I/O operation on closed pipe`` 的 ResourceWarning。
    """
    from inkflow_api.state import build_state
    from inkflow_core.paths import InkFlowPaths
    from inkflow_core.storage import sqlite_url
    from inkflow_source.loader import SourceLoader
    from inkflow_source.registry import SourceRegistry

    paths = InkFlowPaths(tmp_path / "home").ensure()
    settings = Settings()
    settings.source.allow_private_network = True
    settings.js.enabled = True
    settings.js.timeout = 10.0

    state = build_state(
        settings,
        paths=paths,
        database_url=sqlite_url(paths.database_dir / "test.db"),
        registry=SourceRegistry(),
        loader=SourceLoader(),
        session_token="test-token",
    )
    yield state
    await state.shutdown()


def _adapter_from(state, definition: dict) -> LegadoSourceAdapter:
    source = state.loader.load_text(json.dumps(definition, ensure_ascii=False))
    state.library.save_source(source)
    return state.registry.create(source, replace=True)


# ================================================================ 未启用


async def test_js_rule_without_runtime_raises(state, source_with_js: dict, mock_site: str) -> None:
    """没启用 JS 运行时时，``@js:`` 必须**明确报错**。

    返回空会让调用方以为「这个字段本来就没有」，把配置问题伪装成解析问题 ——
    用户会去查书源，而真正的问题在 config.toml。
    """
    adapter = _adapter_from(state, source_with_js)

    with pytest.raises(SourceError) as info:
        await adapter.book_info(f"{mock_site}/book/1")

    assert "未启用" in str(info.value)
    assert "[js]" in str(info.value)


async def test_error_mentions_how_to_enable(state, source_with_js: dict, mock_site: str) -> None:
    """报错要带上「怎么修」，否则用户只知道错了、不知道怎么办。"""
    adapter = _adapter_from(state, source_with_js)

    with pytest.raises(SourceError) as info:
        await adapter.book_info(f"{mock_site}/book/1")

    assert "enabled" in str(info.value)


# ================================================================ 已启用


@requires_node
async def test_js_rule_executes(js_state, source_with_js: dict, mock_site: str) -> None:
    """启用了就能跑通 —— 这是 M3 的核心断言。"""
    adapter = _adapter_from(js_state, source_with_js)

    book = await adapter.book_info(f"{mock_site}/book/1")

    assert book.name == "JS 算出来的书名"


@requires_node
async def test_js_uses_host_encoding_api(js_state, source_with_js: dict, mock_site: str) -> None:
    """宿主 API（java.*）在真实解析链路里可用。"""
    definition = source_with_js
    definition["ruleBookInfo"]["name"] = "@js:java.md5Encode('abc')"
    adapter = _adapter_from(js_state, definition)

    book = await adapter.book_info(f"{mock_site}/book/1")

    assert book.name == "900150983cd24fb0d6963f7d28e17f72"


@requires_node
async def test_js_error_surfaces_as_source_error(
    js_state, source_with_js: dict, mock_site: str
) -> None:
    """规则写错时要抛 SourceError，并带上 kind 便于定位。"""
    definition = source_with_js
    definition["ruleBookInfo"]["name"] = "@js:null.foo"
    adapter = _adapter_from(js_state, definition)

    with pytest.raises(SourceError) as info:
        await adapter.book_info(f"{mock_site}/book/1")

    assert "JS 规则执行失败" in str(info.value)


@requires_node
async def test_js_timeout_surfaces_as_source_error(
    js_state, source_with_js: dict, mock_site: str
) -> None:
    """死循环不能把整个请求挂住。"""
    definition = source_with_js
    definition["ruleBookInfo"]["name"] = "@js:while(true){}"
    js_state.settings.js.timeout = 1.0
    adapter = _adapter_from(js_state, definition)

    with pytest.raises(SourceError) as info:
        await adapter.book_info(f"{mock_site}/book/1")

    assert "timeout" in str(info.value)


@requires_node
async def test_non_js_rules_still_work(js_state, source_with_js: dict, mock_site: str) -> None:
    """启用 JS 不该影响普通规则 —— 同一个书源里其他字段仍是 L1 求值。"""
    adapter = _adapter_from(js_state, source_with_js)

    book = await adapter.book_info(f"{mock_site}/book/1")

    assert book.author == "刘慈欣"


@requires_node
async def test_js_runtime_is_shared_across_sources(js_state, mock_site: str) -> None:
    """多个书源共用一个 sidecar 进程 —— 每个书源起一个太浪费（每个约 30MB）。

    适配器实例是两个（各自持有书源配置），但 `js` 指向同一个运行时。
    """
    first = _adapter_from(js_state, legado_source(mock_site))
    second = _adapter_from(js_state, legado_source(mock_site))

    assert first is not second
    assert first.js is js_state.js
    assert second.js is js_state.js


# ================================================================ 直接求值


@requires_node
async def test_eval_js_field_directly() -> None:
    """绕过网络，直接验证 `_eval_js` 的变量注入。"""
    definition = LegadoBookSource.model_validate(
        {
            "bookSourceName": "直连测试",
            "bookSourceUrl": "https://example.com",
            "ruleBookInfo": {"name": "@js:baseUrl"},
        }
    )
    js = JsRuntime(js_state_config())
    try:
        adapter = LegadoSourceAdapter(
            source=_fake_source(), definition=definition, http=None, js=js
        )
        rule = adapter._rule_book_fields["name"]
        context = RuleContext(base_url="https://example.com/book/1")

        assert await adapter._eval_js(rule, context) == "https://example.com/book/1"
    finally:
        await js.close()


def js_state_config():
    from inkflow_core.config import JsConfig

    return JsConfig(enabled=True, timeout=5.0)


def _fake_source():
    from inkflow_core.models import BookSource, SourceFormat, SourceType

    return BookSource(
        id="src_test",
        name="直连测试",
        url="https://example.com",
        source_type=SourceType.LEGADO,
        source_format=SourceFormat.LEGADO_JSON,
    )
