"""inkflow-api —— HTTP API 服务层。

本包是**唯一**对外暴露的入口：CLI 与 Desktop 都通过它访问业务核心，
不直接 import 业务代码。
"""

from inkflow_api.app import create_app
from inkflow_api.auth import TokenAuthMiddleware, generate_token
from inkflow_api.state import AppState, build_state
from inkflow_core import __version__

# __version__ 由 inkflow-core 转发而来，全项目只有一处定义

__all__ = [
    "AppState",
    "TokenAuthMiddleware",
    "__version__",
    "build_state",
    "create_app",
    "generate_token",
]
