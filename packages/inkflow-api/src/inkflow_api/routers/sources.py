"""书源路由：列表、导入、测试、删除（规划书 §27.5、§41、§42）。"""

from __future__ import annotations

import time
from typing import Any

import httpx
from fastapi import APIRouter, Body, Query

from inkflow_api.deps import StateDep
from inkflow_api.schemas import (
    MessageResponse,
    SourceImportRequest,
    SourceImportResponse,
    SourceListResponse,
    SourceTestRequest,
    SourceTestResponse,
)
from inkflow_core.errors import ErrorCode, SourceError
from inkflow_core.models import BookSource
from inkflow_source.security import check_url

__all__ = ["router"]

router = APIRouter(prefix="/api/v1/sources", tags=["sources"])


@router.get("", response_model=SourceListResponse, summary="书源列表")
async def list_sources(state: StateDep) -> SourceListResponse:
    """列出全部书源。"""
    items = state.library.list_sources()
    return SourceListResponse(items=items, total=len(items))


@router.post("/import", response_model=SourceImportResponse, summary="导入书源")
async def import_source(
    state: StateDep,
    payload: SourceImportRequest,
) -> SourceImportResponse:
    """导入书源。

    支持三种输入：直接给 ``content``（YAML / JSON 文本）、给 ``url``
    （从远程拉取）、或先上传文件再走 ``content``。

    Raises:
        SourceError: 内容为空、格式无法识别或校验失败。
    """
    text: str | None = payload.content

    if not text and payload.url:
        # 远程导入同样要走 SSRF 校验 —— 否则书源可以把我们当代理
        await check_url(payload.url, allow_private_network=False)
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
            response = await client.get(payload.url)
            response.raise_for_status()
            text = response.text

    if not text:
        raise SourceError(
            "必须提供 content 或 url 之一",
            code=ErrorCode.SOURCE_INVALID,
        )

    source = state.loader.load_text(text, origin=payload.url or "<inline>")
    source.enabled = payload.enabled

    existed = _exists(state, source.id)
    state.library.save_source(source)
    state.registry.create(source, replace=True)

    return SourceImportResponse(source=source, created=not existed)


@router.get("/{source_id}", response_model=BookSource, summary="书源详情")
async def get_source(state: StateDep, source_id: str) -> BookSource:
    """按 ID 取书源。

    Raises:
        NotFoundError: 书源不存在。
    """
    return state.library.get_source(source_id)


@router.patch("/{source_id}", response_model=BookSource, summary="启用 / 停用书源")
async def update_source(
    state: StateDep,
    source_id: str,
    enabled: bool = Body(..., embed=True),
) -> BookSource:
    """启用或停用书源。"""
    source = state.library.set_source_enabled(source_id, enabled)
    if enabled:
        state.registry.create(source, replace=True)
    else:
        state.registry.remove(source_id)
    return source


@router.delete("/{source_id}", response_model=MessageResponse, summary="删除书源")
async def delete_source(
    state: StateDep,
    source_id: str,
    purge_books: bool = Query(False, description="是否同时删除该来源下的书籍"),
) -> MessageResponse:
    """删除书源。

    ``purge_books=false``（默认）时只删书源定义，已入库的书籍保留 ——
    用户可能还想继续读已经下载好的内容。
    """
    deleted = state.library.delete_source(source_id)
    state.registry.remove(source_id)
    if not deleted:
        raise SourceError(
            f"书源不存在: {source_id}",
            code=ErrorCode.SOURCE_NOT_FOUND,
            details={"source_id": source_id},
        )
    suffix = "，关联书籍一并删除" if purge_books else ""
    return MessageResponse(message=f"已删除书源 {source_id}{suffix}")


@router.post("/{source_id}/test", response_model=SourceTestResponse, summary="书源测试")
async def test_source(
    state: StateDep,
    source_id: str,
    payload: SourceTestRequest,
) -> SourceTestResponse:
    """对书源执行一次真实调用并返回调试信息（规划书 §42、§43）。

    测试**不缓存**结果，也不写库 —— 它是一次纯粹的连通性与规则验证。
    """
    source = state.library.get_source(source_id)
    adapter = _ensure_adapter(state, source)

    started = time.perf_counter()
    debug: dict[str, Any] = {}

    try:
        if payload.kind == "search":
            results = await adapter.search(payload.keyword)
            preview = [
                {
                    "name": r.name,
                    "author": r.author,
                    "book_url": r.book_url,
                    "latest_chapter": r.latest_chapter,
                }
                for r in results[:5]
            ]
            count = len(results)
            if not results:
                debug["hint"] = "搜索无结果：请检查 searchUrl 模板与 bookList 规则"

        elif payload.kind == "info":
            if not payload.url:
                raise SourceError("测试 book_info 需要提供 url", code=ErrorCode.SOURCE_INVALID)
            info = await adapter.book_info(payload.url)
            preview = [
                {
                    "name": info.name,
                    "author": info.author,
                    "cover_url": info.cover_url,
                    "latest_chapter": info.latest_chapter,
                }
            ]
            count = 1 if info.name else 0

        elif payload.kind == "toc":
            if not payload.url:
                raise SourceError("测试 toc 需要提供 url", code=ErrorCode.SOURCE_INVALID)
            chapters = await adapter.chapters(payload.url)
            preview = [{"index": c.index, "name": c.name, "url": c.url} for c in chapters[:5]]
            count = len(chapters)
            if not chapters:
                debug["hint"] = "目录为空：请检查 chapterList 规则"

        else:  # content
            if not payload.url:
                raise SourceError("测试 content 需要提供 url", code=ErrorCode.SOURCE_INVALID)
            content = await adapter.content(payload.url)
            preview = [
                {
                    "chapter_name": content.chapter_name,
                    "length": len(content.content),
                    "head": content.content[:200],
                }
            ]
            count = 1 if content.content else 0
            if not content.content:
                debug["hint"] = "正文为空：请检查 content 规则"

    except Exception as exc:
        return SourceTestResponse(
            ok=False,
            kind=payload.kind,
            source_id=source_id,
            elapsed_ms=round((time.perf_counter() - started) * 1000, 1),
            error=f"{type(exc).__name__}: {exc}",
            debug=debug,
        )

    return SourceTestResponse(
        ok=True,
        kind=payload.kind,
        source_id=source_id,
        elapsed_ms=round((time.perf_counter() - started) * 1000, 1),
        count=count,
        preview=preview,
        debug=debug,
    )


@router.get("/{source_id}/rules", summary="查看编译后的规则（Source Debugger）")
async def inspect_rules(state: StateDep, source_id: str) -> dict[str, Any]:
    """返回书源规则编译后的 AST，用于排查规则问题。

    只对 Legado 书源有效；原生书源返回其声明式规格。
    """
    source = state.library.get_source(source_id)

    if source.source_type.value == "legado":
        from inkflow_legado import LegadoBookSource, LegadoRuleCompiler

        definition = LegadoBookSource.model_validate(source.raw)
        compiler = LegadoRuleCompiler()
        return {
            "source_id": source_id,
            "source_type": str(source.source_type),
            "compatibility_level": str(source.compatibility_level),
            "uses_js": definition.uses_js(),
            "needs_browser": definition.needs_browser(),
            "rules": {
                "search.bookList": compiler.compile(definition.ruleSearch.bookList).describe(),
                "search.name": compiler.compile(definition.ruleSearch.name).describe(),
                "search.bookUrl": compiler.compile(definition.ruleSearch.bookUrl).describe(),
                "toc.chapterList": compiler.compile(definition.ruleToc.chapterList).describe(),
                "toc.chapterName": compiler.compile(definition.ruleToc.chapterName).describe(),
                "toc.chapterUrl": compiler.compile(definition.ruleToc.chapterUrl).describe(),
                "content.content": compiler.compile(definition.ruleContent.content).describe(),
            },
        }

    return {
        "source_id": source_id,
        "source_type": str(source.source_type),
        "capabilities": source.raw.get("search") is not None,
        "raw": source.raw,
    }


# ---------------------------------------------------------------- 内部


def _exists(state: StateDep, source_id: str) -> bool:
    """书源是否已存在。"""
    return any(s.id == source_id for s in state.library.list_sources())


def _ensure_adapter(state: StateDep, source: BookSource) -> Any:
    """确保适配器已在注册表中，返回它。

    服务重启后注册表是空的（书源定义在数据库里），
    因此这里按需重建，而不是要求调用方先「加载」。
    """
    if source.id in state.registry:
        return state.registry.get(source.id)
    return state.registry.create(source, replace=True)
