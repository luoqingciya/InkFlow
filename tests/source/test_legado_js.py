"""Legado L2（``@js:`` 规则）端到端测试。

跑的是**真的 Node sidecar**：书源规则里写 ``@js:``，经过适配器 →
JS 运行时 → 沙箱执行 → 结果回到解析流程。

这里特意不用 mock 顶掉运行时 —— 要验证的正是「这条链路通不通」。
"""

from __future__ import annotations

import json

import pytest
from inkflow_js_runtime import JsRuntime, find_node

from inkflow_core.config import JsConfig, Settings
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


# ================================================================ 宿主取值 API
#
# 这几个是从真实书源集合里统计出来的高频 API（样本 1363 条）：
#   java.getString 75 次、java.put 27 次、java.get 30 次


def _js_adapter(js, source_def: dict, http=None):
    """构造一个带 JS 运行时的适配器。

    ``http`` 不传时**别假设「没有客户端」** —— 基类的 ``http`` 是惰性属性，
    传 None 会按书源配置创建真实客户端。凡是会走 ``java.ajax`` 的用例
    都必须注入假客户端，不要让测试真发网络请求。
    """
    from inkflow_core.models import BookSource, SourceFormat, SourceType

    definition = LegadoBookSource.model_validate(source_def)
    source = BookSource(
        id="src_js",
        name="JS 测试",
        url="https://example.com",
        source_type=SourceType.LEGADO,
        source_format=SourceFormat.LEGADO_JSON,
    )
    return LegadoSourceAdapter(source=source, definition=definition, http=http, js=js)


@requires_node
async def test_get_string_reads_json_path() -> None:
    """`java.getString('$.x')` 从当前 JSON 上下文取值。"""
    definition = {
        "bookSourceName": "t",
        "bookSourceUrl": "https://e.com",
        "ruleBookInfo": {"name": "x"},
    }
    js = JsRuntime(JsConfig(enabled=True, timeout=5.0))
    try:
        adapter = _js_adapter(js, definition)
        adapter._current_context = RuleContext(data={"bookId": "12345"})
        result = await adapter._eval_js(
            adapter.compiler.compile("@js:java.getString('$.bookId')"),
            RuleContext(data={"bookId": "12345"}),
        )
    finally:
        await js.close()

    assert result == "12345"


@requires_node
async def test_get_string_reads_css_selector() -> None:
    """同一 API 也能用 CSS 选择器从 HTML 取值。"""
    from inkflow_source.parsers import html as html_parser

    definition = {
        "bookSourceName": "t",
        "bookSourceUrl": "https://e.com",
        "ruleBookInfo": {"name": "x"},
    }
    doc = html_parser.parse_html('<h1 class="title">三体</h1>')
    js = JsRuntime(JsConfig(enabled=True, timeout=5.0))
    try:
        adapter = _js_adapter(js, definition)
        result = await adapter._eval_js(
            adapter.compiler.compile("@js:java.getString('h1.title@text')"),
            RuleContext(doc=doc),
        )
    finally:
        await js.close()

    assert result == "三体"


@requires_node
async def test_get_string_missing_returns_empty() -> None:
    """取不到值时返回空串，不是抛错 —— 书源里常用 `||` 兜底。"""
    definition = {
        "bookSourceName": "t",
        "bookSourceUrl": "https://e.com",
        "ruleBookInfo": {"name": "x"},
    }
    js = JsRuntime(JsConfig(enabled=True, timeout=5.0))
    try:
        adapter = _js_adapter(js, definition)
        result = await adapter._eval_js(
            adapter.compiler.compile("@js:java.getString('$.nope')"),
            RuleContext(data={"bookId": "1"}),
        )
    finally:
        await js.close()

    assert result == ""


@requires_node
async def test_put_and_get_share_across_rules() -> None:
    """`java.put` / `java.get` 是**书源级**变量，跨规则共享。

    真实书源就是这么用的：`tocUrl` 里 put 一个 bookId，`chapterUrl` 里 get 出来。
    """
    definition = {
        "bookSourceName": "t",
        "bookSourceUrl": "https://e.com",
        "ruleBookInfo": {"name": "x"},
    }
    js = JsRuntime(JsConfig(enabled=True, timeout=5.0))
    try:
        adapter = _js_adapter(js, definition)

        await adapter._eval_js(
            adapter.compiler.compile("@js:java.put('bid', '42')"),
            RuleContext(data={}),
        )
        result = await adapter._eval_js(
            adapter.compiler.compile("@js:java.get('bid')"),
            RuleContext(data={}),
        )
    finally:
        await js.close()

    assert result == "42"


@requires_node
async def test_get_unknown_key_returns_empty() -> None:
    definition = {
        "bookSourceName": "t",
        "bookSourceUrl": "https://e.com",
        "ruleBookInfo": {"name": "x"},
    }
    js = JsRuntime(JsConfig(enabled=True, timeout=5.0))
    try:
        adapter = _js_adapter(js, definition)
        result = await adapter._eval_js(
            adapter.compiler.compile("@js:java.get('never-set')"),
            RuleContext(data={}),
        )
    finally:
        await js.close()

    assert result == ""


@requires_node
async def test_variables_are_isolated_per_adapter() -> None:
    """变量跟着 adapter 走，不同书源之间不串味。"""
    definition = {
        "bookSourceName": "t",
        "bookSourceUrl": "https://e.com",
        "ruleBookInfo": {"name": "x"},
    }
    js = JsRuntime(JsConfig(enabled=True, timeout=5.0))
    try:
        first = _js_adapter(js, definition)
        second = _js_adapter(js, definition)

        await first._eval_js(first.compiler.compile("@js:java.put('k', 'first')"), RuleContext())
        result = await second._eval_js(second.compiler.compile("@js:java.get('k')"), RuleContext())
    finally:
        await js.close()

    assert result == ""


@requires_node
async def test_to_num_chapter() -> None:
    """中文数字转阿拉伯数字（样本里 20 处）。"""
    definition = {
        "bookSourceName": "t",
        "bookSourceUrl": "https://e.com",
        "ruleBookInfo": {"name": "x"},
    }
    js = JsRuntime(JsConfig(enabled=True, timeout=5.0))
    try:
        adapter = _js_adapter(js, definition)
        cases = {"三": "3", "十二": "12", "二十四": "24", "一千零二十四": "1024"}
        results = {
            text: await adapter._eval_js(
                adapter.compiler.compile(f"@js:java.toNumChapter('{text}')"), RuleContext()
            )
            for text in cases
        }
    finally:
        await js.close()

    assert results == cases


# ================================================================ 请求数上限
#
# ``max_requests`` 限制的是**单次规则执行**能扇出多少网络请求（ADR-023）。
# 只数网络请求 —— getString / put / get 是本地操作，不计入。


class _FakeResponse:
    def __init__(self, text: str = "ok", status: int = 200) -> None:
        self.text = text
        self.status = status
        self.ok = status < 400


class _FakeHttp:
    """只记录调用，不发请求。"""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def request(self, method: str, url: str, data=None, headers=None) -> _FakeResponse:
        self.calls.append(url)
        return _FakeResponse()


_LIMIT_DEF = {
    "bookSourceName": "t",
    "bookSourceUrl": "https://e.com",
    "ruleBookInfo": {"name": "x"},
}


def _ajax_code(count: int) -> str:
    calls = ";".join(f"java.ajax('https://e.com/{i}')" for i in range(count))
    return f"@js:{calls};'done'"


@requires_node
async def test_requests_under_limit_go_through() -> None:
    """没到上限时正常放行 —— 别把正常书源掐死。"""
    js = JsRuntime(JsConfig(enabled=True, timeout=5.0, max_requests=3))
    http = _FakeHttp()
    try:
        adapter = _js_adapter(js, _LIMIT_DEF, http=http)
        result = await adapter._eval_js(adapter.compiler.compile(_ajax_code(3)), RuleContext())
    finally:
        await js.close()

    assert result == "done"
    assert len(http.calls) == 3


@requires_node
async def test_exceeding_limit_is_reported() -> None:
    """超过上限要**明确报错**，并且真的把请求拦住。"""
    js = JsRuntime(JsConfig(enabled=True, timeout=5.0, max_requests=2))
    http = _FakeHttp()
    try:
        adapter = _js_adapter(js, _LIMIT_DEF, http=http)
        with pytest.raises(SourceError) as info:
            await adapter._eval_js(adapter.compiler.compile(_ajax_code(3)), RuleContext())
    finally:
        await js.close()

    assert "超过上限" in str(info.value)
    # 只放行 2 次 —— 第 3 次根本没发出去
    assert len(http.calls) == 2


@requires_node
async def test_limit_resets_per_eval() -> None:
    """计数按**单次求值**重置：上一次用满，不该影响下一次。"""
    js = JsRuntime(JsConfig(enabled=True, timeout=5.0, max_requests=2))
    http = _FakeHttp()
    try:
        adapter = _js_adapter(js, _LIMIT_DEF, http=http)
        rule = adapter.compiler.compile(_ajax_code(2))
        first = await adapter._eval_js(rule, RuleContext())
        second = await adapter._eval_js(rule, RuleContext())
    finally:
        await js.close()

    assert first == "done"
    assert second == "done"
    assert len(http.calls) == 4


@requires_node
async def test_zero_means_unlimited() -> None:
    """``0`` = 不限制（ADR-023）。"""
    js = JsRuntime(JsConfig(enabled=True, timeout=5.0, max_requests=0))
    http = _FakeHttp()
    try:
        adapter = _js_adapter(js, _LIMIT_DEF, http=http)
        result = await adapter._eval_js(adapter.compiler.compile(_ajax_code(5)), RuleContext())
    finally:
        await js.close()

    assert result == "done"
    assert len(http.calls) == 5


@requires_node
async def test_local_host_calls_do_not_consume_budget() -> None:
    """``getString`` / ``put`` / ``get`` 是本地操作，不占网络请求配额。

    上限设成 1：如果本地调用也被计数，这次 ``java.ajax`` 就会被误拦。
    """
    js = JsRuntime(JsConfig(enabled=True, timeout=5.0, max_requests=1))
    http = _FakeHttp()
    try:
        adapter = _js_adapter(js, _LIMIT_DEF, http=http)
        code = (
            "@js:java.getString('$.a');java.put('k','v');java.get('k');"
            "java.ajax('https://e.com/1');'done'"
        )
        result = await adapter._eval_js(
            adapter.compiler.compile(code), RuleContext(data={"a": "1"})
        )
    finally:
        await js.close()

    assert result == "done"
    assert len(http.calls) == 1
