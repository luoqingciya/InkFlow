"""Legado 的 ``webView`` / ``webJs`` 走浏览器（L3）。

用**测试桩**当引擎 —— 桩做真实 HTTP，所以「URL 有没有解析对、有没有真的走
浏览器这条路」都能真验，不必下 270MB 浏览器。

真实引擎的行为由 ``tests/browser/test_playwright.py`` 用同一批契约保证。
"""

from __future__ import annotations

import pytest

from inkflow_core.errors import SourceError
from inkflow_legado import LegadoSourceAdapter, build_legado_source
from inkflow_source.http import HttpClient
from tests.browser.stub import StubBrowserProvider
from tests.sources_data import legado_source

pytestmark = pytest.mark.source


class _RecordingBrowser(StubBrowserProvider):
    """记录被请求的 URL 与脚本，用来断言「真的走了浏览器这条路」。"""

    def __init__(self) -> None:
        super().__init__()
        self.fetched: list[str] = []
        self.scripts: list[str | None] = []

    async def fetch_html(
        self, url: str, *, js: str | None = None, timeout: float | None = None
    ) -> str:
        self.fetched.append(url)
        self.scripts.append(js)
        return await super().fetch_html(url, js=js, timeout=timeout)


def _adapter(definition: dict, browser: StubBrowserProvider | None = None) -> LegadoSourceAdapter:
    """构造适配器。

    显式建 HTTP 客户端并放行内网 —— mock 站点跑在 127.0.0.1 上，
    默认会被 SSRF 防护挡掉。
    """
    source = build_legado_source(definition)
    http = HttpClient.from_source(source, allow_private_network=True)
    return LegadoSourceAdapter.from_source(source, http, None, browser)


# ================================================================ webView 选项


async def test_webview_option_routes_through_browser(mock_site: str) -> None:
    """``,{'webView': true}`` 走浏览器。

    同时钉住 URL：**选项后缀不能跟着 URL 一起发出去** —— 单引号写法标准
    ``json`` 读不了，读不了就会把整段 ``{'webView': true}`` 当成 URL 的一部分。
    """
    definition = legado_source(mock_site)
    definition["searchUrl"] = "/search?q={{key}},{'webView': true}"
    browser = _RecordingBrowser()
    adapter = _adapter(definition, browser)
    try:
        results = await adapter.search("三体")
    finally:
        await browser.close()

    assert len(results) == 3
    assert browser.fetched == [f"{mock_site}/search?q=三体"]
    assert "webView" not in browser.fetched[0]
    assert "{" not in browser.fetched[0]


async def test_webview_without_browser_is_reported(mock_site: str) -> None:
    """没启用浏览器时要**明确报错**，不能退回普通请求。

    退回会拿到没渲染过的页面，看起来像「书源规则失效」——
    把配置问题伪装成解析问题。
    """
    definition = legado_source(mock_site)
    definition["searchUrl"] = "/search?q={{key}},{'webView': true}"
    adapter = _adapter(definition)

    with pytest.raises(SourceError) as info:
        await adapter.search("三体")

    assert "浏览器" in str(info.value)
    assert "[browser]" in str(info.value)


async def test_double_quoted_option_also_works(mock_site: str) -> None:
    """双引号写法同样要走浏览器 —— 两种写法在真实书源里都有。"""
    definition = legado_source(mock_site)
    definition["searchUrl"] = '/search?q={{key}},{"webView": true}'
    browser = _RecordingBrowser()
    adapter = _adapter(definition, browser)
    try:
        await adapter.search("三体")
    finally:
        await browser.close()

    assert browser.fetched == [f"{mock_site}/search?q=三体"]


# ================================================================ webJs


async def test_web_js_is_handed_to_the_browser(mock_site: str) -> None:
    """``webJs`` 要传给浏览器执行。

    桩不支持脚本，所以这里断言的是**路由**：脚本确实递到了浏览器，
    而且失败是**看得见**的（明确报错，不是静默忽略）。
    """
    definition = legado_source(mock_site)
    definition["ruleContent"]["webJs"] = "document.title"
    browser = _RecordingBrowser()
    adapter = _adapter(definition, browser)
    try:
        with pytest.raises(SourceError) as info:
            await adapter.content(f"{mock_site}/chapter/1")
    finally:
        await browser.close()

    assert browser.scripts == ["document.title"]
    assert "不能在页面里执行脚本" in str(info.value)


async def test_web_js_absent_keeps_plain_fetch(mock_site: str) -> None:
    """没有 webJs 时不该往浏览器绕 —— 那要多起一个几百 MB 的进程。"""
    browser = _RecordingBrowser()
    adapter = _adapter(legado_source(mock_site), browser)
    try:
        await adapter.content(f"{mock_site}/chapter/1")
    finally:
        await browser.close()

    assert browser.fetched == []


# ================================================================ 装配


async def test_assembly_injects_browser_into_adapter(tmp_path) -> None:
    """装配层要把浏览器挂到适配器上。

    光有适配器能力、装配层没接上，L3 书源照样跑不起来 —— 这条钉的就是那根线。
    """
    from inkflow_api.state import build_state
    from inkflow_core.config import Settings
    from inkflow_core.paths import InkFlowPaths
    from inkflow_core.storage import sqlite_url
    from inkflow_source.loader import SourceLoader
    from inkflow_source.registry import SourceRegistry

    settings = Settings()
    settings.browser.enabled = True
    paths = InkFlowPaths(tmp_path / "home").ensure()
    state = build_state(
        settings,
        paths=paths,
        database_url=sqlite_url(paths.database_dir / "test.db"),
        registry=SourceRegistry(),
        loader=SourceLoader(),
        session_token="test-token",
    )
    try:
        assert state.browser is not None
        source = build_legado_source(legado_source("https://x.test"))
        state.library.save_source(source)

        adapter = state.registry.create(source, replace=True)

        assert adapter.browser is state.browser
    finally:
        await state.shutdown()


async def test_assembly_leaves_browser_off_by_default(tmp_path) -> None:
    """默认不启用 —— 浏览器要按需下载，不该谁都装。"""
    from inkflow_api.state import build_state
    from inkflow_core.config import Settings
    from inkflow_core.paths import InkFlowPaths
    from inkflow_core.storage import sqlite_url
    from inkflow_source.loader import SourceLoader
    from inkflow_source.registry import SourceRegistry

    paths = InkFlowPaths(tmp_path / "home").ensure()
    state = build_state(
        Settings(),
        paths=paths,
        database_url=sqlite_url(paths.database_dir / "test.db"),
        registry=SourceRegistry(),
        loader=SourceLoader(),
        session_token="test-token",
    )
    try:
        assert state.browser is None
        source = build_legado_source(legado_source("https://x.test"))
        state.library.save_source(source)

        adapter = state.registry.create(source, replace=True)

        assert adapter.browser is None
    finally:
        await state.shutdown()
