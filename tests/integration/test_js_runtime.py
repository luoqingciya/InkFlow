"""JS runtime 客户端测试（Legado L2）。

这里跑的是**真的 Node 子进程** —— 不用 mock 顶掉 sidecar。
要验证的东西（超时能不能打断、沙箱里能不能摸到 process、崩溃能不能
被发现）全都是进程行为，mock 掉就什么都测不到了。
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest

from inkflow_core.config import JsConfig
from inkflow_js_runtime import JsRuntime, JsRuntimeError, JsUnavailableError, find_node

pytestmark = pytest.mark.integration

#: 没装 Node 的机器上跳过 —— 但 CI 装了，所以这不是「假装通过」
requires_node = pytest.mark.skipif(find_node() is None, reason="机器上没有 Node.js")


@pytest.fixture
async def runtime() -> AsyncGenerator[JsRuntime]:
    """一个已经启动的运行时，用例结束后关闭。"""
    js = JsRuntime(JsConfig(enabled=True, timeout=5.0))
    yield js
    await js.close()


# ================================================================ 基本执行


@requires_node
async def test_evaluates_expression(runtime: JsRuntime) -> None:
    """取代码的完成值 —— Legado 规则体就是这个语义。"""
    assert await runtime.eval("1 + 1") == 2


@requires_node
async def test_returns_last_statement_value(runtime: JsRuntime) -> None:
    assert await runtime.eval("var a = 1; a + 41") == 42


@requires_node
async def test_start_is_idempotent_with_handshake(runtime: JsRuntime) -> None:
    """重复 start 不该把就绪消息再读一遍 —— 那会吞掉下一条真正的响应。"""
    await runtime.start()
    await runtime.start()

    assert await runtime.eval("2 + 2") == 4


@requires_node
async def test_slow_startup_is_not_reported_as_rule_timeout(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """启动慢要报「启动超时」，**不能**报成「规则执行超时」。

    这两件事混在一起，查错方向就全错了 —— Windows CI 上那次偶发超时
    一直没查出来，就是因为分不清是哪一个。
    """
    stub = tmp_path / "silent.mjs"
    stub.write_text("setTimeout(() => {}, 60000);\n", encoding="utf-8")
    monkeypatch.setattr("inkflow_js_runtime.client.SIDECAR_ENTRY", stub)
    monkeypatch.setattr(JsRuntime, "STARTUP_TIMEOUT", 0.5)

    runtime = JsRuntime(JsConfig(enabled=True, timeout=5.0))
    try:
        with pytest.raises(JsUnavailableError) as info:
            await runtime.start()
    finally:
        await runtime.close()

    message = str(info.value)
    assert "启动超时" in message
    assert "规则" not in message


@requires_node
async def test_returns_string(runtime: JsRuntime) -> None:
    assert await runtime.eval("'三体' + 'Ⅱ'") == "三体Ⅱ"


@requires_node
async def test_returns_object(runtime: JsRuntime) -> None:
    assert await runtime.eval("({name: '三体', year: 2006})") == {"name": "三体", "year": 2006}


@requires_node
async def test_undefined_becomes_null(runtime: JsRuntime) -> None:
    """undefined 没法塞进 JSON，统一成 null。"""
    assert await runtime.eval("undefined") is None


@requires_node
async def test_accepts_variables(runtime: JsRuntime) -> None:
    """书源规则里 `{{key}}` 之类会变成注入的变量。"""
    result = await runtime.eval("key + '/' + page", variables={"key": "三体", "page": 2})

    assert result == "三体/2"


# ================================================================ 宿主 API


@requires_node
async def test_md5_matches_known_value(runtime: JsRuntime) -> None:
    """对已知向量断言 —— 只测「返回了字符串」证明不了算法对。"""
    assert await runtime.eval("java.md5Encode('abc')") == "900150983cd24fb0d6963f7d28e17f72"


@requires_node
async def test_md5_16_is_middle_slice(runtime: JsRuntime) -> None:
    assert await runtime.eval("java.md5Encode16('abc')") == "3cd24fb0d6963f7d"


@requires_node
async def test_base64_roundtrip(runtime: JsRuntime) -> None:
    result = await runtime.eval("java.base64Decode(java.base64Encode('三体'))")

    assert result == "三体"


@requires_node
async def test_hex_roundtrip(runtime: JsRuntime) -> None:
    assert await runtime.eval("java.hexDecodeToString(java.hexEncodeToString('hi'))") == "hi"


@requires_node
async def test_time_format(runtime: JsRuntime) -> None:
    """0 毫秒在 UTC 是 1970-01-01，本地时区会偏移，所以只断言格式。"""
    result = await runtime.eval("java.timeFormat(0)")

    assert isinstance(result, str)
    assert len(result) == 19
    assert result[4] == "-" and result[13] == ":"


# ================================================================ 响应大小


@requires_node
async def test_large_response_is_returned() -> None:
    """响应超过 64KB 也要能拿到。

    书源规则完全可能返回一整页 HTML 或一段长 JSON —— 而 asyncio 的
    StreamReader 默认行长上限只有 64KB，不调大就会在 readline 直接抛错。
    """
    js = JsRuntime(JsConfig(enabled=True, timeout=5.0))
    try:
        result = await js.eval("'x'.repeat(200000)")
    finally:
        await js.close()

    assert isinstance(result, str)
    assert len(result) == 200000


@requires_node
async def test_oversized_response_is_reported() -> None:
    """超过 max_response_size 要报明确错误，而不是漏出 ValueError。

    ``max_response_size`` 是可配的；配了就必须真的生效，且失败要看得见。
    """
    js = JsRuntime(JsConfig(enabled=True, timeout=5.0, max_response_size="64KB"))
    try:
        with pytest.raises(JsRuntimeError) as info:
            await js.eval("'x'.repeat(200000)")
    finally:
        await js.close()

    assert info.value.kind == "too_large"


# ================================================================ 沙箱隔离


@requires_node
@pytest.mark.parametrize(
    "expression", ["typeof process", "typeof require", "typeof globalThis.process"]
)
async def test_host_globals_are_not_visible(runtime: JsRuntime, expression: str) -> None:
    """沙箱里摸不到 Node 的宿主对象。

    注意这只证明「没有直接注入」—— vm 不是权限边界，真正的边界是
    「独立进程 + 进程里没有敏感数据」。见 sidecar/sandbox.js 的说明。
    """
    assert await runtime.eval(expression) == "undefined"


@requires_node
async def test_java_object_is_injected(runtime: JsRuntime) -> None:
    """反过来，宿主 API 必须在。"""
    assert await runtime.eval("typeof java.ajax") == "function"


# ================================================================ 失败路径


@requires_node
async def test_timeout_is_reported(runtime: JsRuntime) -> None:
    """死循环必须能被打断，且错误类型要能区分出来。"""
    with pytest.raises(JsRuntimeError) as info:
        await runtime.eval("while(true){}", timeout=0.8)

    assert info.value.kind == "timeout"


@requires_node
async def test_syntax_error_is_reported(runtime: JsRuntime) -> None:
    with pytest.raises(JsRuntimeError) as info:
        await runtime.eval("this is not javascript")

    assert info.value.kind == "syntax"


@requires_node
async def test_runtime_error_is_reported(runtime: JsRuntime) -> None:
    with pytest.raises(JsRuntimeError) as info:
        await runtime.eval("null.foo")

    assert info.value.kind == "runtime"


@requires_node
async def test_empty_code_is_rejected(runtime: JsRuntime) -> None:
    with pytest.raises(JsRuntimeError) as info:
        await runtime.eval("")

    assert info.value.kind == "invalid_params"


@requires_node
async def test_runtime_recovers_after_error(runtime: JsRuntime) -> None:
    """一次失败不该污染后续执行 —— 进程要还能用。"""
    with pytest.raises(JsRuntimeError):
        await runtime.eval("null.foo")

    assert await runtime.eval("1 + 1") == 2


# ================================================================ 进程复用


@requires_node
async def test_process_is_reused(runtime: JsRuntime) -> None:
    """同一个运行时实例不该每次 eval 都起新进程。"""
    await runtime.eval("1")
    first = runtime._process

    await runtime.eval("2")

    assert runtime._process is first


@requires_node
async def test_close_is_idempotent(runtime: JsRuntime) -> None:
    await runtime.eval("1")

    await runtime.close()
    await runtime.close()

    assert not runtime.running


@requires_node
async def test_restarts_after_close(runtime: JsRuntime) -> None:
    """关掉之后再 eval 应该能自动重启，而不是报错。"""
    await runtime.close()

    assert await runtime.eval("1 + 1") == 2


# ================================================================ 反向请求


@requires_node
async def test_host_request_is_forwarded() -> None:
    """`java.ajax` 必须回调 Python，而不是 sidecar 自己联网。

    这条是安全模型的支点：网络请求走回 Python，SSRF 防护与限速才生效。
    """
    seen: list[dict] = []

    async def host_request(params: dict) -> dict:
        seen.append(params)
        return {"ok": True, "body": "来自 Python 的响应"}

    js = JsRuntime(JsConfig(enabled=True, timeout=5.0), host_request=host_request)
    try:
        result = await js.eval("java.ajax('https://example.com/api')")
    finally:
        await js.close()

    assert result == "来自 Python 的响应"
    assert seen == [
        {"url": "https://example.com/api", "method": "GET", "body": None, "headers": None}
    ]


@requires_node
async def test_host_request_failure_surfaces_in_js() -> None:
    """宿主请求失败时，JS 侧要抛错而不是拿到空字符串。"""

    async def host_request(params: dict) -> dict:
        return {"ok": False, "error": "目标被拒绝"}

    js = JsRuntime(JsConfig(enabled=True, timeout=5.0), host_request=host_request)
    try:
        with pytest.raises(JsRuntimeError) as info:
            await js.eval("java.ajax('https://blocked.example/')")
    finally:
        await js.close()

    assert "目标被拒绝" in str(info.value)


@requires_node
async def test_without_host_handler_ajax_fails() -> None:
    """没接宿主回调时，java.ajax 要给明确错误 —— 不能静默返回空。"""
    js = JsRuntime(JsConfig(enabled=True, timeout=5.0))
    try:
        with pytest.raises(JsRuntimeError) as info:
            await js.eval("java.ajax('https://example.com/')")
    finally:
        await js.close()

    assert "宿主" in str(info.value)


# ================================================================ 不可用


async def test_missing_node_raises_unavailable() -> None:
    """找不到 node 要抛专门的异常类型。

    调用方靠它区分「环境不具备」与「规则写错了」—— 后者是书源的问题，
    前者是部署的问题，混在一起会让人查错方向。
    """
    js = JsRuntime(JsConfig(enabled=True), node="/nonexistent/node-binary")

    with pytest.raises(JsUnavailableError):
        await js.eval("1")
