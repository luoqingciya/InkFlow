"""定位正在运行的 InkFlow 服务。

端口默认由系统分配（``port = 0``），命令行无法猜。因此服务启动时会把
实际地址与 token 写进 ``~/.inkflow/server.json``，CLI 读这个文件。

优先级：环境变量 > 握手文件 > 内置默认值。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from inkflow_core.paths import get_paths

__all__ = ["ENV_TOKEN", "ENV_URL", "ServerLocation", "discover"]

ENV_URL = "INKFLOW_API_URL"
ENV_TOKEN = "INKFLOW_TOKEN"

DEFAULT_URL = "http://127.0.0.1:8765"


@dataclass(slots=True)
class ServerLocation:
    """服务位置与凭据。"""

    base_url: str
    token: str | None = None
    #: 来源说明，用于 ``--verbose`` 时告知用户「我是怎么找到服务的」
    origin: str = "default"

    @property
    def ws_url(self) -> str:
        """对应的 WebSocket 基地址。"""
        if self.base_url.startswith("https://"):
            return "wss://" + self.base_url[len("https://") :]
        if self.base_url.startswith("http://"):
            return "ws://" + self.base_url[len("http://") :]
        return self.base_url


def discover(*, url: str | None = None, token: str | None = None) -> ServerLocation:
    """确定要连接的服务。

    Args:
        url: 显式指定的地址（命令行 ``--url``）。
        token: 显式指定的 token（命令行 ``--token``）。
    """
    if url:
        return ServerLocation(
            base_url=url.rstrip("/"),
            token=token or os.environ.get(ENV_TOKEN),
            origin="命令行参数",
        )

    env_url = os.environ.get(ENV_URL)
    if env_url:
        return ServerLocation(
            base_url=env_url.rstrip("/"),
            token=token or os.environ.get(ENV_TOKEN),
            origin=f"环境变量 {ENV_URL}",
        )

    handshake = _read_handshake()
    if handshake is not None:
        host = handshake.get("host", "127.0.0.1")
        port = handshake.get("port")
        if isinstance(port, int) and port > 0:
            raw_token = handshake.get("token")
            return ServerLocation(
                base_url=f"http://{host}:{port}",
                token=token or (raw_token if isinstance(raw_token, str) else None),
                origin="握手文件",
            )

    return ServerLocation(base_url=DEFAULT_URL, token=token, origin="默认地址")


def _read_handshake() -> dict[str, object] | None:
    """读取 ``~/.inkflow/server.json``。"""
    path = get_paths().home / "server.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def handshake_path() -> Path:
    """握手文件路径，供错误提示使用。"""
    return get_paths().home / "server.json"
