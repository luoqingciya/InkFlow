"""inkflow-cli —— 命令行客户端。

本包**不实现任何业务逻辑**，只是 ``inkflow-api`` 的一层薄壳：
每条命令对应一个 HTTP 请求。这样可以保证 CLI 与 Desktop 的行为
永远一致 —— 它们消费的是同一个接口。
"""

from inkflow_cli.client import ApiError, InkFlowClient
from inkflow_cli.discovery import ServerLocation, discover
from inkflow_core import __version__

# __version__ 由 inkflow-core 转发而来，全项目只有一处定义

__all__ = [
    "ApiError",
    "InkFlowClient",
    "ServerLocation",
    "__version__",
    "discover",
]
