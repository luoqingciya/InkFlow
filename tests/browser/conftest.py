"""浏览器测试共用的夹具。

``page_url`` / ``closed_port_url`` / ``hanging_url`` 三个测试桩与真实引擎
都要用，所以放在这里而不是某个测试模块里。
"""

from __future__ import annotations

import socket
import threading
from collections.abc import Iterator

import pytest


@pytest.fixture
def page_url(mock_site: str) -> str:
    """mock 站点上一个**真实存在**的页面（根路径是 404）。"""
    return f"{mock_site}/book/1"


@pytest.fixture
def closed_port_url() -> str:
    """刚释放的端口 —— 连它必定被拒。"""
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    _, port = probe.getsockname()
    probe.close()
    return f"http://127.0.0.1:{port}/"


@pytest.fixture
def hanging_url() -> Iterator[str]:
    """接受连接但从不响应的本地地址 —— 用来验超时真的生效。"""
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    host, port = server.getsockname()
    held: list[socket.socket] = []

    def _accept() -> None:
        try:
            conn, _ = server.accept()
        except OSError:
            return
        held.append(conn)  # 留着不关，也不回数据

    threading.Thread(target=_accept, daemon=True).start()
    try:
        yield f"http://{host}:{port}/"
    finally:
        for conn in held:
            conn.close()
        server.close()
