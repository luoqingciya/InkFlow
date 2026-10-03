"""inkflow-js-runtime —— Legado L2 的 JS 执行能力。

Python 侧只负责**进程管理**与**协议配对**；真正执行 JS 的是
``sidecar/`` 下的 Node 程序。两者的分工与安全边界见
``sidecar/sandbox.js`` 顶部的说明。
"""

from inkflow_core import __version__
from inkflow_js_runtime.client import (
    ENV_NODE,
    JsRuntime,
    JsRuntimeError,
    JsUnavailableError,
    find_node,
)

__all__ = [
    "__version__",
    # 客户端
    "JsRuntime",
    "JsRuntimeError",
    "JsUnavailableError",
    "find_node",
    "ENV_NODE",
]
