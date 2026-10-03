"""按需下载浏览器。

默认分发不带浏览器（ADR-024）—— 271MB 不该让所有用户都下，首次启用时再装。

**冻结构建不支持**：单文件 exe 里既没有 playwright 也没有 pip，下载不了。
这一点在 :func:`install_browser` 里**明确报出来**，而不是给一条用户执行不了的
命令。
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from inkflow_browser_playwright.paths import browsers_dir
from inkflow_browser_playwright.provider import BROWSER_TARGET
from inkflow_core.browser import BrowserUnavailableError
from inkflow_core.paths import is_frozen

if TYPE_CHECKING:  # pragma: no cover
    from inkflow_core.config import BrowserConfig

__all__ = ["BROWSERS_PATH_ENV", "DOWNLOAD_HOST_ENV", "browser_installed", "install_browser"]

#: playwright 读这两个环境变量决定「装到哪」与「从哪下」。
BROWSERS_PATH_ENV = "PLAYWRIGHT_BROWSERS_PATH"
DOWNLOAD_HOST_ENV = "PLAYWRIGHT_DOWNLOAD_HOST"


def browser_installed(config: BrowserConfig | None = None, *, target: str = BROWSER_TARGET) -> bool:
    """浏览器是否已装到目标目录。

    **宽松判定**：只看有没有对应构建的目录，不校验版本。版本对不上时
    ``start()`` 会报错并给出安装命令 —— 那一层兜得住。
    """
    directory = browsers_dir(config)
    if not directory.is_dir():
        return False
    return any(directory.glob(f"{target.replace('-', '_')}-*"))


def install_browser(
    config: BrowserConfig | None = None,
    *,
    target: str = BROWSER_TARGET,
    on_progress: Callable[[str], None] | None = None,
) -> Path:
    """下载浏览器到 ``browsers_dir(config)``，返回安装目录。

    **同步阻塞**：270MB 要下几十秒到几分钟。调用方自己决定放线程还是任务里。

    Args:
        config: 浏览器配置；``download_host`` 非空时用它换源。
        target: 要装的构建。默认只装 headless 外壳（271MB，完整版 433MB）。
        on_progress: 进度回调，收到的是给人看的字符串。

    Raises:
        BrowserUnavailableError: 冻结构建、没装 playwright、或下载失败。
    """
    directory = browsers_dir(config)

    if is_frozen():
        raise BrowserUnavailableError(
            "这个构建（单文件可执行程序）没有带浏览器引擎，无法在运行时下载。\n"
            "需要浏览器渲染的书源只在 pip / uv 安装的环境里可用：\n"
            '  pip install "inkflow-browser-playwright[playwright]"'
        )

    try:
        import playwright  # noqa: F401
    except ImportError as exc:
        raise BrowserUnavailableError(
            "未安装 playwright，无法下载浏览器。执行：\n"
            '  pip install "inkflow-browser-playwright[playwright]"'
        ) from exc

    directory.mkdir(parents=True, exist_ok=True)

    env = dict(os.environ)
    env[BROWSERS_PATH_ENV] = str(directory)
    if config is not None and config.download_host:
        env[DOWNLOAD_HOST_ENV] = config.download_host

    report = on_progress or (lambda _message: None)
    report(f"正在下载 {target}（约 270MB）到 {directory}")

    # 不捕获输出：让 playwright 的进度条直接显示在调用方的终端上，
    # 否则用户要对着几分钟的空白等。
    result = subprocess.run(
        [sys.executable, "-m", "playwright", "install", target],
        env=env,
        check=False,
    )
    if result.returncode != 0:
        raise BrowserUnavailableError(
            f"下载浏览器失败（退出码 {result.returncode}）。\n"
            f"网络不通时可以配置 [browser] download_host 换源，或手动执行：\n"
            f"  python -m playwright install {target}"
        )

    report("浏览器安装完成")
    return directory
