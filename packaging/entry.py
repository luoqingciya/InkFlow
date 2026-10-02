"""PyInstaller 打包入口。

单独放一个入口文件而不是直接用 ``inkflow_api.main:main``：
PyInstaller 需要一个真实的脚本文件做分析起点，指向模块名会让它
把整个 site-packages 都扫一遍。
"""

from __future__ import annotations

import multiprocessing
import sys

from inkflow_api.main import main

if __name__ == "__main__":
    # PyInstaller 打包后若代码里用到 multiprocessing，必须调用这个，
    # 否则子进程会重新执行整个入口脚本，表现为「进程无限自我复制」。
    multiprocessing.freeze_support()
    sys.exit(main())
