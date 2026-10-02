"""SQLite 连接与生命周期管理。

MVP 阶段直接用 SQLite（规划书 §25）：单文件、零运维、够快。
将来换 PostgreSQL 只需替换 URL 与少量方言细节，表结构本身是标准的。
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from inkflow_core.paths import InkFlowPaths, get_paths
from inkflow_core.storage.tables import Base

__all__ = ["Database", "sqlite_url"]


def sqlite_url(path: Path) -> str:
    """把文件路径转成 SQLAlchemy 的 SQLite URL。

    Windows 盘符路径需要 ``as_posix()``，否则反斜杠会被当成转义字符。
    """
    return f"sqlite:///{path.as_posix()}"


class Database:
    """数据库句柄。

    Args:
        url: SQLAlchemy 连接串；省略时使用 ``~/.inkflow/database/inkflow.db``。
        echo: 是否打印 SQL（排障用）。
        paths: 数据目录对象，省略时取进程级默认值。
    """

    def __init__(
        self,
        url: str | None = None,
        *,
        echo: bool = False,
        paths: InkFlowPaths | None = None,
    ) -> None:
        self.paths = paths or get_paths()
        if url is None:
            self.paths.database_dir.mkdir(parents=True, exist_ok=True)
            url = sqlite_url(self.paths.database_file)

        self.url = url
        self._engine: Engine = create_engine(
            url,
            echo=echo,
            future=True,
            # SQLite 默认禁止跨线程复用连接，FastAPI 的线程池需要放开
            connect_args={"check_same_thread": False} if url.startswith("sqlite") else {},
        )
        if url.startswith("sqlite"):
            self._install_sqlite_pragmas(self._engine)

        self._session_factory = sessionmaker(
            bind=self._engine, expire_on_commit=False, class_=Session
        )

    @staticmethod
    def _install_sqlite_pragmas(engine: Engine) -> None:
        """启用外键约束与 WAL 日志模式。

        SQLite 默认**不**强制外键，不打开的话 ``ondelete="CASCADE"`` 形同虚设。
        WAL 让读写可以并发，下载任务写库时不会阻塞界面查询。
        """

        @event.listens_for(engine, "connect")
        def _on_connect(dbapi_conn: Any, _record: Any) -> None:
            cursor = dbapi_conn.cursor()
            try:
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA synchronous=NORMAL")
            finally:
                cursor.close()

    @property
    def engine(self) -> Engine:
        return self._engine

    def create_all(self) -> None:
        """按当前表定义建表（幂等，不删数据）。"""
        Base.metadata.create_all(self._engine)

    def drop_all(self) -> None:
        """删除全部表。仅用于测试。"""
        Base.metadata.drop_all(self._engine)

    @contextmanager
    def session(self) -> Iterator[Session]:
        """事务性会话。

        正常退出自动 commit，异常自动 rollback 并向上抛出 ——
        调用方不需要写 try/except 处理回滚。
        """
        session = self._session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def dispose(self) -> None:
        """释放连接池。"""
        self._engine.dispose()
