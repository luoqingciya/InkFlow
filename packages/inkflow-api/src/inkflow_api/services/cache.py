"""HTTP 响应缓存（规划书 §26）。

缓存的是**原始响应字节**，不是解析后的结果 —— 书源规则会变，
缓存解析结果会让改完规则之后仍旧命中旧数据。

实现落在装配层而不是 ``inkflow-source``：缓存要落 SQLite，而书源引擎
不该背持久化职责（它连 sqlalchemy 都不依赖）。协议在 source 定义、
实现在此注入，依赖方向仍然只有 ``core ← source ← api``。
"""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from inkflow_core.storage import Database
from inkflow_core.storage.tables import HttpCacheRow
from inkflow_core.utils import ensure_utc, utcnow
from inkflow_source.http import HttpResponse

__all__ = ["SqliteHttpCache"]


class SqliteHttpCache:
    """基于 SQLite 的 HTTP 响应缓存。

    实现 ``inkflow_source.http.HttpCache`` 协议。

    Args:
        db: 数据库句柄。
        max_size_bytes: 容量上限；超出后按最近命中时间淘汰最旧条目。
        default_ttl: 默认存活秒数；``None`` 表示写入的条目不过期。
    """

    def __init__(
        self,
        db: Database,
        *,
        max_size_bytes: int | None = None,
        default_ttl: int | None = None,
    ) -> None:
        self.db = db
        self.max_size_bytes = max_size_bytes
        self.default_ttl = default_ttl

    async def get(self, key: str) -> HttpResponse | None:
        """取缓存。未命中或已过期返回 ``None``。

        命中时刷新 ``hit_at`` —— 这是 LRU 淘汰的依据。
        """
        now = utcnow()
        with self.db.session() as session:
            row = session.get(HttpCacheRow, key)
            if row is None:
                return None

            expires_at = ensure_utc(row.expires_at)
            if expires_at is not None and expires_at <= now:
                # 惰性删除：过期条目不必靠后台任务清扫，读到就扔
                session.delete(row)
                return None

            row.hit_at = now
            return HttpResponse(
                url=row.url,
                status=row.status,
                headers=_load_headers(row.headers),
                content=row.body,
                from_cache=True,
            )

    async def set(self, key: str, response: HttpResponse, *, ttl: int | None = None) -> None:
        """写缓存，并在超出容量时淘汰最久未命中的条目。"""
        now = utcnow()
        effective_ttl = self.default_ttl if ttl is None else ttl
        # 区分「不过期」（None）与「立即过期」（0）—— 用 if effective_ttl
        # 判真会把 0 也当成不过期
        expires_at = None if effective_ttl is None else now + timedelta(seconds=effective_ttl)

        with self.db.session() as session:
            row = session.get(HttpCacheRow, key)
            if row is None:
                row = HttpCacheRow(key=key, created_at=now)
                session.add(row)
            row.url = response.url
            row.status = response.status
            row.headers = json.dumps(response.headers, ensure_ascii=False)
            row.body = response.content
            row.size = len(response.content)
            row.expires_at = expires_at
            self._evict(session)

    def clear(self) -> int:
        """清空缓存，返回删除的条目数。"""
        with self.db.session() as session:
            removed = session.scalar(select(func.count()).select_from(HttpCacheRow)) or 0
            session.execute(delete(HttpCacheRow))
        return int(removed)

    def stats(self) -> dict[str, Any]:
        """缓存概况，供 ``/api/v1/system/info`` 展示。"""
        now = utcnow()
        with self.db.session() as session:
            entries = session.scalar(select(func.count()).select_from(HttpCacheRow)) or 0
            size_bytes = session.scalar(select(func.coalesce(func.sum(HttpCacheRow.size), 0))) or 0
            expired = (
                session.scalar(
                    select(func.count())
                    .select_from(HttpCacheRow)
                    .where(
                        HttpCacheRow.expires_at.is_not(None),
                        HttpCacheRow.expires_at <= now,
                    )
                )
                or 0
            )
        return {
            "entries": entries,
            "size_bytes": size_bytes,
            "expired_entries": expired,
            "max_size_bytes": self.max_size_bytes,
        }

    # -- 内部 --------------------------------------------------------------

    def _evict(self, session: Session) -> int:
        """按最近命中时间淘汰，直到总量落回上限以内。"""
        if self.max_size_bytes is None:
            return 0

        total = session.scalar(select(func.coalesce(func.sum(HttpCacheRow.size), 0))) or 0
        if total <= self.max_size_bytes:
            return 0

        # hit_at 为空表示从未命中，按写入时间排 —— 它是最该被淘汰的那批
        stalest = session.scalars(
            select(HttpCacheRow).order_by(
                func.coalesce(HttpCacheRow.hit_at, HttpCacheRow.created_at).asc()
            )
        ).all()

        removed = 0
        for row in stalest:
            if total <= self.max_size_bytes:
                break
            total -= row.size
            session.delete(row)
            removed += 1
        return removed


def _load_headers(text: str | None) -> dict[str, str]:
    """容错解析 headers：坏数据退回空字典，不让缓存把请求打挂。"""
    if not text:
        return {}
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}
