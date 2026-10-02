"""定位正在运行的 InkFlow 服务。

端口默认由系统分配（``port = 0``），命令行无法猜。因此服务启动时会把
实际地址与 token 写进数据目录下的 ``server.json``，CLI 读这个文件。

数据目录是**便携**的（默认在运行目录下），所以 CLI 与 Desktop 的
运行目录不同时，握手文件也不在同一处。这里会遍历所有候选目录去找 ——
只要有一个能找到就能连上。

优先级：环境变量 > 握手文件 > 内置默认值。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from inkflow_core.paths import candidate_homes, get_paths

__all__ = ["ENV_TOKEN", "ENV_URL", "ServerLocation", "discover", "handshake_path"]

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

    found = _read_handshake()
    if found is not None:
        path, handshake = found
        host = handshake.get("host", "127.0.0.1")
        port = handshake.get("port")
        if isinstance(port, int) and port > 0:
            raw_token = handshake.get("token")
            return ServerLocation(
                base_url=f"http://{host}:{port}",
                token=token or (raw_token if isinstance(raw_token, str) else None),
                origin=f"握手文件 {path}",
            )

    return ServerLocation(base_url=DEFAULT_URL, token=token, origin="默认地址")


def _read_handshake() -> tuple[Path, dict[str, object]] | None:
    """在所有候选数据目录里找握手文件。

    只看当前数据目录是不够的：CLI 可能从别的目录启动，
    而 Desktop 拉起的后端把握手文件写在了它自己的运行目录下。
    """
    for home in candidate_homes():
        path = home / "server.json"
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            # 文件存在但读不了（权限 / 写了一半），换下一个候选
            continue
        if isinstance(data, dict):
            return path, data
    return None


def handshake_path() -> Path:
    """当前数据目录下的握手文件路径，供错误提示使用。"""
    return get_paths().handshake_file
