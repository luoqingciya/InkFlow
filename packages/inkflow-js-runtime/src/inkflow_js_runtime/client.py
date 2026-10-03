"""Node sidecar 的 Python 客户端（Legado L2）。

**为什么是独立进程。** 不可信的书源 JS 不能跑在 Python 主进程里 ——
它可能死循环、吃满内存、或者利用引擎漏洞。sidecar 崩了只是它自己崩，
主进程能发现、能重启、能报错。

**为什么网络要回调 Python。** `java.ajax` 不由 sidecar 自己发请求，
而是通过反向 RPC 交回 Python 的 ``HttpClient`` —— 这样 SSRF 防护、
协议白名单、限速、缓存全部照旧生效。让 sidecar 自己联网等于在安全模型上开洞。

**为什么 sidecar 用同步 stdio。** Legado 的 ``java.ajax(url)`` 是同步调用，
书源代码不会写 ``await``。sidecar 内部用 ``fs.readSync`` 阻塞等响应；
Python 这侧仍是 asyncio，靠「先处理反向请求、再收最终结果」的循环配对。
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import shutil
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from inkflow_core.config import JsConfig

__all__ = ["JsRuntime", "JsRuntimeError", "JsUnavailableError", "find_node"]

logger = logging.getLogger("inkflow.js")

SIDECAR_DIR = Path(__file__).parent / "sidecar"
SIDECAR_ENTRY = SIDECAR_DIR / "main.js"

#: 指向 node 可执行文件的环境变量（机器上 node 不在 PATH 时用）
ENV_NODE = "INKFLOW_NODE"

#: 反向请求的处理函数签名：(params) -> result
HostRequestHandler = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


class JsRuntimeError(RuntimeError):
    """JS 规则执行失败。"""

    def __init__(self, message: str, *, kind: str = "runtime") -> None:
        super().__init__(message)
        self.kind = kind


class JsUnavailableError(JsRuntimeError):
    """JS 运行时不可用（没装 Node、sidecar 启动失败等）。

    单独一个类型，是为了让调用方能明确区分「规则写错了」与
    「环境不具备」—— 后者不该被当成书源的问题。
    """

    def __init__(self, message: str) -> None:
        super().__init__(message, kind="unavailable")


def find_node() -> str | None:
    """定位 node 可执行文件。找不到返回 ``None``。"""
    override = os.environ.get(ENV_NODE)
    if override:
        candidate = Path(override).expanduser()
        return str(candidate) if candidate.exists() else None
    return shutil.which("node")


class JsRuntime:
    """sidecar 的生命周期与请求配对。

    Args:
        config: ``[js]`` 段配置。
        host_request: 处理 ``java.ajax`` 一类反向请求的回调。
        node: node 可执行文件路径；省略时自动查找。
    """

    def __init__(
        self,
        config: JsConfig,
        *,
        host_request: HostRequestHandler | None = None,
        node: str | None = None,
    ) -> None:
        self.config = config
        self.host_request = host_request
        self.node = node or find_node()

        self._process: asyncio.subprocess.Process | None = None
        self._lock = asyncio.Lock()
        self._sequence = 0
        # 保存引用：不持有的话任务可能被 GC 回收，stderr 就没人读了
        self._stderr_task: asyncio.Task[None] | None = None

    # -- 生命周期 ----------------------------------------------------------

    @property
    def running(self) -> bool:
        return self._process is not None and self._process.returncode is None

    async def start(self) -> None:
        """启动 sidecar。

        Raises:
            JsUnavailableError: 找不到 node、或 sidecar 入口不存在。
        """
        if self.running:
            return
        if self.node is None:
            raise JsUnavailableError(
                f"找不到 node 可执行文件。请安装 Node.js 20+，或用环境变量 {ENV_NODE} 指向它。"
            )
        if not SIDECAR_ENTRY.exists():
            raise JsUnavailableError(f"sidecar 入口缺失：{SIDECAR_ENTRY}")

        try:
            self._process = await asyncio.create_subprocess_exec(
                self.node,
                # 进程级内存上限。vm 管不了内存，这是唯一可靠的地方。
                f"--max-old-space-size={self.config.max_memory_mb}",
                str(SIDECAR_ENTRY),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(SIDECAR_DIR),
                # 读取上限 = 配置里的响应上限。asyncio 默认只有 64KB，
                # 而书源规则完全可能返回一整页 HTML —— 那样会在 readline
                # 抛 ValueError，变成一个跟协议无关的报错。
                limit=self.config.max_response_bytes,
            )
        except OSError as exc:
            raise JsUnavailableError(f"启动 sidecar 失败：{exc}") from exc

        # stderr 只用来记日志，读完即弃 —— 不读会把它塞满导致 sidecar 阻塞
        self._stderr_task = asyncio.create_task(self._drain_stderr())
        logger.info("JS sidecar 已启动 pid=%s", self._process.pid)

    async def close(self) -> None:
        """关闭 sidecar。已经退出或从未启动时静默返回。"""
        process = self._process
        self._process = None
        if process is None or process.returncode is not None:
            return

        if process.stdin is not None:
            with contextlib.suppress(Exception):
                process.stdin.write(b'{"id":0,"method":"shutdown"}\n')
                await process.stdin.drain()

        try:
            await asyncio.wait_for(process.wait(), timeout=3.0)
        except TimeoutError:
            process.kill()
            with contextlib.suppress(Exception):
                await process.wait()
        logger.info("JS sidecar 已关闭")

    async def _drain_stderr(self) -> None:
        """把 sidecar 的日志转进 Python 日志，避免管道塞满。"""
        process = self._process
        if process is None or process.stderr is None:
            return
        while True:
            line = await process.stderr.readline()
            if not line:
                return
            logger.debug("sidecar: %s", line.decode("utf-8", errors="replace").rstrip())

    # -- 执行 --------------------------------------------------------------

    async def eval(
        self,
        code: str,
        *,
        variables: dict[str, Any] | None = None,
        timeout: float | None = None,
        host_request: HostRequestHandler | None = None,
    ) -> Any:
        """执行一段 JS，返回它的完成值。

        Args:
            code: 规则代码。
            variables: 注入沙箱的全局变量。
            timeout: 覆盖配置里的超时。
            host_request: 本次调用使用的反向请求处理器。**按调用传入**而不是
                绑在实例上 —— 一个 sidecar 进程被多个书源共用，处理器需要
                知道「现在是谁在请求」，否则拿不到正确的 HTTP 客户端。

        Raises:
            JsUnavailableError: 运行时不可用。
            JsRuntimeError: 规则执行失败（超时 / 语法 / 运行时错误）。
        """
        async with self._lock:
            await self.start()
            return await self._eval_locked(code, variables or {}, timeout, host_request)

    async def _eval_locked(
        self,
        code: str,
        variables: dict[str, Any],
        timeout: float | None,
        host_request: HostRequestHandler | None,
    ) -> Any:
        process = self._process
        if process is None or process.stdin is None or process.stdout is None:
            raise JsUnavailableError("sidecar 未在运行")

        effective_timeout = self.config.timeout if timeout is None else timeout
        self._sequence += 1
        request_id = self._sequence

        payload = {
            "id": request_id,
            "method": "eval",
            "params": {
                "code": code,
                "vars": variables,
                # sidecar 自己也要有超时，否则死循环会一直占着进程
                "timeout": int(effective_timeout * 1000),
            },
        }
        process.stdin.write((json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"))
        await process.stdin.drain()

        handler = host_request or self.host_request
        try:
            return await asyncio.wait_for(
                self._pump(request_id, handler), timeout=effective_timeout + 5.0
            )
        except TimeoutError as exc:
            # Python 侧的兜底超时（比 sidecar 的宽 5s）。走到这里说明
            # sidecar 卡死了，进程状态不可信，直接丢掉让它下次重启。
            await self._discard_process()
            raise JsRuntimeError(
                f"JS 执行超时（{effective_timeout + 5.0:.0f}s 无响应）", kind="timeout"
            ) from exc

    async def _pump(self, request_id: int, handler: HostRequestHandler | None) -> Any:
        """读消息直到拿到本次请求的结果，期间处理反向请求。"""
        process = self._process
        assert process is not None and process.stdout is not None

        while True:
            try:
                line = await process.stdout.readline()
            except ValueError as exc:
                # 单行超过 ``limit``（= max_response_size）时 StreamReader 抛
                # ValueError。不接住会变成一个跟协议无关的报错，也看不出是超限。
                await self._discard_process()
                raise JsRuntimeError(
                    f"JS 响应超过上限（{self.config.max_response_size}）",
                    kind="too_large",
                ) from exc
            if not line:
                self._process = None
                raise JsUnavailableError("sidecar 意外退出（stdout 已关闭）")

            try:
                message = json.loads(line.decode("utf-8"))
            except json.JSONDecodeError:
                logger.warning("忽略 sidecar 的非法输出：%r", line[:200])
                continue

            if message.get("method") == "host.request":
                # 必须**就地**处理：sidecar 正阻塞等这条响应
                await self._answer_host_request(message, handler)
                continue

            if message.get("id") != request_id:
                logger.warning("忽略 ID 不匹配的消息：%s", message.get("id"))
                continue

            if message.get("ok"):
                return message.get("result")

            error = message.get("error") or {}
            raise JsRuntimeError(
                str(error.get("message", "JS 执行失败")),
                kind=str(error.get("kind", "runtime")),
            )

    async def _answer_host_request(
        self,
        message: dict[str, Any],
        handler: HostRequestHandler | None,
    ) -> None:
        """处理 ``java.ajax`` 一类反向请求，并把结果写回去。"""
        request_id = message.get("id")
        params = message.get("params") or {}

        if handler is None:
            result: dict[str, Any] = {"ok": False, "error": "宿主未提供请求能力"}
        else:
            try:
                result = await handler(params)
            except Exception as exc:  # 宿主异常不该让 sidecar 卡住
                logger.warning("宿主请求失败：%s", exc)
                result = {"ok": False, "error": str(exc)}

        process = self._process
        if process is None or process.stdin is None:
            return
        with contextlib.suppress(Exception):
            reply = {"id": request_id, "result": result}
            process.stdin.write((json.dumps(reply, ensure_ascii=False) + "\n").encode("utf-8"))
            await process.stdin.drain()

    async def _discard_process(self) -> None:
        """丢弃当前进程 —— 卡死或状态可疑时用，下次 eval 会重启。"""
        process = self._process
        self._process = None
        if process is None:
            return
        with contextlib.suppress(Exception):
            process.kill()
        with contextlib.suppress(Exception):
            await process.wait()
