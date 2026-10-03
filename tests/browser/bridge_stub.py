"""桌面端浏览器桥的测试替身。

按真实协议实现（见 ``desktop/src/main/browser-bridge.ts``）：用一个真 HTTP
服务把「渲染」这一步用普通 GET 顶掉 —— 协议、鉴权、超时、错误形状都能真验，
不需要真的跑 Electron。

它**不能**验的：Electron 那边的隐藏窗口、Cookie 共享、JS 执行。
那些只有实机跑桌面端才算数。
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import httpx

__all__ = ["BridgeStub", "start_bridge_stub"]

#: 与桌面端约定的头名。
HEADER_TOKEN = "X-Inkflow-Token"


class BridgeStub:
    """运行中的假桥。"""

    def __init__(self, server: ThreadingHTTPServer, thread: threading.Thread, token: str) -> None:
        self._server = server
        self._thread = thread
        self.token = token
        host, port = server.server_address[:2]
        if isinstance(host, bytes):  # 某些平台返回 bytes
            host = host.decode("ascii")
        self.url = f"http://{host}:{port}"
        #: 收到过的 ``/render`` 请求，供断言
        self.renders: list[dict[str, Any]] = []

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)


def start_bridge_stub(token: str = "test-token") -> BridgeStub:
    """启动假桥。"""
    shared: dict[str, Any] = {"token": token, "renders": []}

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args: Any) -> None:
            """静音 —— 默认会往 stderr 刷每一行请求。"""

        # -- 基础 ----------------------------------------------------------

        def _send(self, status: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("content-type", "application/json; charset=utf-8")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _reject_unless_authorized(self) -> bool:
            """token 不对就直接回 401 并返回 False。"""
            if self.headers.get(HEADER_TOKEN) == shared["token"]:
                return True
            self._send(401, {"ok": False, "error": "token 不匹配"})
            return False

        # -- 路由 ----------------------------------------------------------

        def do_GET(self) -> None:
            if not self._reject_unless_authorized():
                return
            if self.path == "/health":
                self._send(200, {"ok": True})
                return
            if self.path == "/cookies":
                self._send(
                    200,
                    {
                        "ok": True,
                        "cookies": [{"name": "sid", "value": "1", "domain": "x.test", "path": "/"}],
                    },
                )
                return
            self._send(404, {"ok": False, "error": f"未知路径 {self.path}"})

        def do_POST(self) -> None:
            if not self._reject_unless_authorized():
                return
            if self.path != "/render":
                self._send(404, {"ok": False, "error": f"未知路径 {self.path}"})
                return

            length = int(self.headers.get("content-length") or 0)
            raw = self.rfile.read(length) if length else b"{}"
            try:
                request = json.loads(raw.decode("utf-8"))
            except ValueError:
                self._send(400, {"ok": False, "error": "请求体不是合法 JSON"})
                return

            shared["renders"].append(request)
            self._render(request)

        def _render(self, request: dict[str, Any]) -> None:
            """把「渲染」用普通 GET 顶掉 —— 拿真实 HTML，但**不跑页面脚本**。"""
            url = str(request.get("url") or "")
            timeout = float(request.get("timeout") or 30)
            try:
                response = httpx.get(url, timeout=timeout, follow_redirects=True)
            except httpx.HTTPError as exc:
                # 渲染失败用 200 + ok:false —— 桥没坏，是这一次没成
                self._send(200, {"ok": False, "error": f"渲染失败：{exc}"})
                return
            self._send(200, {"ok": True, "html": response.text})

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    stub = BridgeStub(server, thread, token)
    stub.renders = shared["renders"]
    return stub
