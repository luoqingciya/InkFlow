"""数据目录约定。

所有运行时数据集中在 ``~/.inkflow`` 下，可用 ``INKFLOW_HOME`` 环境变量整体重定向
（测试与便携版分发依赖这一点）。
"""

from __future__ import annotations

import os
from pathlib import Path

__all__ = ["InkFlowPaths", "get_paths", "inkflow_home"]

ENV_HOME = "INKFLOW_HOME"


def inkflow_home() -> Path:
    """返回 InkFlow 数据根目录。

    优先取 ``INKFLOW_HOME``，否则为 ``~/.inkflow``。
    """
    override = os.environ.get(ENV_HOME)
    if override:
        return Path(override).expanduser().resolve()
    return Path.home() / ".inkflow"


class InkFlowPaths:
    """集中管理数据目录下的各级路径。

    ``~/.inkflow`` 布局::

        ~/.inkflow/
        ├── config/          运行时生成的配置
        ├── database/        inkflow.db
        ├── cache/           HTTP / 章节正文缓存
        ├── downloads/       下载中间产物
        ├── books/           按书籍归档的原始章节数据
        ├── exports/         导出的 TXT / EPUB
        ├── logs/
        └── sources/         用户导入的书源
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
