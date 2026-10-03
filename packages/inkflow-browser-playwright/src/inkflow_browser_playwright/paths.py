"""浏览器安装位置。

放在**数据目录**下（``<数据目录>/browsers/``），与 ADR-015 的便携原则一致 ——
「拷走整个目录即可迁移」。浏览器若不在数据目录里，拷走之后 L3 就失效了。

配置了 ``[browser] install_dir`` 时以它为准，方便多份安装共享同一份浏览器。
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from inkflow_core.paths import inkflow_home

if TYPE_CHECKING:  # pragma: no cover
    from inkflow_core.config import BrowserConfig

__all__ = ["browsers_dir"]


def browsers_dir(config: BrowserConfig | None = None) -> Path:
    """返回浏览器安装目录。**不保证目录存在**。"""
    if config is not None and config.install_dir:
        return Path(config.install_dir).expanduser()
    return inkflow_home() / "browsers"
