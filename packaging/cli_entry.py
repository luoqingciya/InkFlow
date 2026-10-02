"""PyInstaller 打包入口：命令行客户端。

CLI 是**纯 HTTP 消费者**，不依赖 source / legado / api / export，
所以它的可执行文件比后端小得多。
"""

from __future__ import annotations

import multiprocessing
import sys

from inkflow_cli.main import main

if __name__ == "__main__":
    # 打包后若用到 multiprocessing，必须调用它，否则子进程会重新执行整个入口
    multiprocessing.freeze_support()
    sys.exit(main())
