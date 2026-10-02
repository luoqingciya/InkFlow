"""Mock 书站（规划书 §70）。

测试**不应该**请求真实网站 —— 站点一改版，CI 就整片红，而且不可重复。
这里用标准库起一个只读的本地 HTTP 服务，返回固定的 HTML 夹具。
"""

from __future__ import annotations

import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

__all__ = ["start_mock_site", "MockSite", "FIXTURE_DIR"]

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "mock-site"

#: 1×1 的 PNG。图片端点直接吐它 —— 测试要的是「能下到一个图片字节流」，
#: 不需要真实图像内容，也不该为它引入图像库。
TINY_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d494844520000000100000001"
    "08060000001f15c4890000000a49444154789c6300010000"
    "0500010d0a2db40000000049454e44ae426082"
)


class _Handler(BaseHTTPRequestHandler):
    """把路径映射到夹具文件。"""

    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)

        # 封面与正文插图：任何 /cover/ 或 /img/ 下的路径都返回同一张 PNG
        if parsed.path.startswith(("/cover/", "/img/")):
            self._send_bytes(TINY_PNG, "image/png")
            return

        body = self._resolve(parsed.path, parse_qs(parsed.query))

        if body is None:
            self.send_error(404, "Not Found")
            return

        self._send_bytes(body.encode("utf-8"), "text/html; charset=utf-8")

    def _send_bytes(self, payload: bytes, content_type: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    @staticmethod
    def _resolve(path: str, query: dict[str, list[str]]) -> str | None:
        """路径 → 夹具内容。"""
        if path == "/search":
            return (FIXTURE_DIR / "search.html").read_text(encoding="utf-8")
        if path == "/book/1":
            return (FIXTURE_DIR / "book.html").read_text(encoding="utf-8")
        if path == "/book/1/toc":
            page = (query.get("page") or ["1"])[0]
            name = "toc-page2.html" if page == "2" else "toc.html"
            return (FIXTURE_DIR / name).read_text(encoding="utf-8")
        if path.startswith("/chapter/"):
            return (FIXTURE_DIR / "chapter.html").read_text(encoding="utf-8")
        return None

    def log_message(self, *args: object) -> None:
        """静默访问日志，避免污染测试输出。"""


class MockSite:
    """运行中的 mock 站点。"""

    def __init__(self, server: ThreadingHTTPServer, thread: threading.Thread) -> None:
        self._server = server
        self._thread = thread
        host, port = server.server_address[:2]
        if isinstance(host, bytes):  # 某些平台返回 bytes
            host = host.decode("ascii")
        self.url = f"http://{host}:{port}"

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)


def start_mock_site(port: int = 0) -> MockSite:
    """启动 mock 站点。

    Args:
        port: 监听端口；``0`` 表示由系统分配空闲端口（测试用）。
    """
    server = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return MockSite(server, thread)


def main() -> None:
    """手动起一个 mock 站点，用于配合 ``sources/test/mock-site.yaml`` 调试。"""
    import argparse

    parser = argparse.ArgumentParser(description="启动 InkFlow 测试用 mock 书站")
    parser.add_argument("--port", type=int, default=8765, help="监听端口")
    args = parser.parse_args()

    site = start_mock_site(args.port)
    print(f"mock 书站已启动：{site.url}")
    print("按 Ctrl+C 停止")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        site.stop()


if __name__ == "__main__":  # pragma: no cover
    main()
