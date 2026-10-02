"""数据目录约定。

**便携优先**：数据默认放在「运行目录」下的 ``.inkflow``，
拷贝整个程序目录即可迁移，不需要去用户主目录里翻。

解析顺序：

1. ``INKFLOW_HOME`` 环境变量 —— 显式指定（测试、特殊部署）
2. 运行目录下的 ``.inkflow`` —— 便携模式
3. ``~/.inkflow`` —— 兜底（运行目录不可写时）

「运行目录」的判定：

* PyInstaller 打包后 → 可执行文件所在目录
* 源码运行 → 当前工作目录

第 3 步不是多余的：macOS 的 ``.app`` 内部、部分 Linux 安装位置都是只读的，
硬要往里写只会让程序起不来。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

__all__ = ["InkFlowPaths", "get_paths", "inkflow_home", "ENV_HOME"]

ENV_HOME = "INKFLOW_HOME"

#: 数据目录名（相对运行目录）
HOME_DIR_NAME = ".inkflow"

_resolved_home: Path | None = None


def is_frozen() -> bool:
    """当前是否运行在 PyInstaller 打包产物里。"""
    return bool(getattr(sys, "frozen", False))


def runtime_dir() -> Path:
    """程序运行所在目录。

    打包后是**可执行文件所在目录**（不是进程 cwd —— 从快捷方式启动时
    cwd 可能是任意位置）；源码运行则是当前工作目录。
    """
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path.cwd()


def _try_prepare(directory: Path) -> bool:
    """尝试创建目录并确认可写。

    只做 ``os.access`` 检查是不够的 —— Windows 上对目录的写权限判断不可靠，
    而 macOS 的 ``.app`` 内部需要真的尝试写入才能确定。
    """
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError:
        return False

    probe = directory / ".write-probe"
    try:
        probe.write_text("", encoding="utf-8")
        probe.unlink()
    except OSError:
        return False
    return True


def candidate_homes() -> list[Path]:
    """按优先级列出候选数据目录。"""
    return [
        runtime_dir() / HOME_DIR_NAME,
        Path.home() / HOME_DIR_NAME,
    ]


def _resolve_home() -> Path:
    override = os.environ.get(ENV_HOME)
    if override:
        return Path(override).expanduser().resolve()

    for candidate in candidate_homes():
        if _try_prepare(candidate):
            return candidate.resolve()

    # 理论上到不了这里（用户主目录总能创建），留个明确的兜底
    return Path.home() / HOME_DIR_NAME


def inkflow_home() -> Path:
    """返回 InkFlow 数据根目录（结果缓存）。"""
    global _resolved_home
    if _resolved_home is None:
        _resolved_home = _resolve_home()
    return _resolved_home


def reset_home_cache() -> None:
    """清空缓存，让下次调用重新解析。

    测试与「切换数据目录」这类场景需要它。
    """
    global _resolved_home
    _resolved_home = None


class InkFlowPaths:
    """集中管理数据目录下的各级路径。

    ``<运行目录>/.inkflow`` 布局::

        .inkflow/
        ├── config/          运行时生成的配置
        ├── database/        inkflow.db
        ├── cache/           HTTP / 章节正文缓存
        ├── downloads/       下载中间产物
        ├── books/           按书籍归档的原始章节数据
        ├── exports/         导出的 TXT / EPUB
        ├── logs/
        ├── sources/         用户导入的书源
        └── server.json      后端握手信息（端口 + token）
    """

    def __init__(self, home: Path | None = None) -> None:
        self.home = home or inkflow_home()

    # -- 一级目录 ----------------------------------------------------------

    @property
    def config_dir(self) -> Path:
        return self.home / "config"

    @property
    def database_dir(self) -> Path:
        return self.home / "database"

    @property
    def cache_dir(self) -> Path:
        return self.home / "cache"

    @property
    def downloads_dir(self) -> Path:
        return self.home / "downloads"

    @property
    def books_dir(self) -> Path:
        return self.home / "books"

    @property
    def exports_dir(self) -> Path:
        return self.home / "exports"

    @property
    def logs_dir(self) -> Path:
        return self.home / "logs"

    @property
    def sources_dir(self) -> Path:
        return self.home / "sources"

    # -- 具体文件 ----------------------------------------------------------

    @property
    def database_file(self) -> Path:
        return self.database_dir / "inkflow.db"

    @property
    def config_file(self) -> Path:
        return self.config_dir / "config.toml"

    @property
    def handshake_file(self) -> Path:
        """后端启动后写入的握手文件，CLI 靠它发现正在运行的服务。"""
        return self.home / "server.json"

    @property
    def http_cache_dir(self) -> Path:
        return self.cache_dir / "http"

    @property
    def content_cache_dir(self) -> Path:
        return self.cache_dir / "content"

    # -- 操作 --------------------------------------------------------------

    def ensure(self) -> InkFlowPaths:
        """创建全部目录（幂等）。"""
        for directory in (
            self.home,
            self.config_dir,
            self.database_dir,
            self.cache_dir,
            self.downloads_dir,
            self.books_dir,
            self.exports_dir,
            self.logs_dir,
            self.sources_dir,
            self.http_cache_dir,
            self.content_cache_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)
        return self

    def book_dir(self, book_id: str) -> Path:
        """单本书的归档目录。"""
        return self.books_dir / book_id


_default_paths: InkFlowPaths | None = None


def get_paths() -> InkFlowPaths:
    """返回进程级默认路径对象。"""
    global _default_paths
    if _default_paths is None:
        _default_paths = InkFlowPaths()
    return _default_paths
