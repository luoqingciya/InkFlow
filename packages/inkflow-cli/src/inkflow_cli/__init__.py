"""inkflow-cli —— 命令行客户端。

本包**不实现任何业务逻辑**，只是 ``inkflow-api`` 的一层薄壳：
每条命令对应一个 HTTP 请求。这样可以保证 CLI 与 Desktop 的行为
永远一致 —— 它们消费的是同一个接口。
"""

from inkflow_cli.client import ApiError, InkFlowClient
from inkflow_cli.discovery import ServerLocation, discover

__version__ = "0.1.0"

__all__ = [
    "ApiError",
    "InkFlowClient",
    "ServerLocation",
    "__version__",
    "discover",
]
