"""原生书源适配器（规划书 §5 Level 1）。"""

from __future__ import annotations

from typing import Any
from urllib.parse import urljoin

from inkflow_core.errors import ErrorCode, SourceError
from inkflow_core.models import (
    BookResult,
    BookSource,
    ChapterResult,
    ContentResult,
)
from inkflow_source.adapter import BaseSourceAdapter
from inkflow_source.http import HttpClient
from inkflow_source.native.schema import NativeSourceSpec
from inkflow_source.normalizer import ContentNormalizer, NormalizeRules
from inkflow_source.parsers import html as html_parser
from inkflow_source.parsers import text as text_parser

__all__ = ["NativeSourceAdapter"]


def _render(
    value: str, *, keyword: str = "", page: int = 1, extra: dict[str, Any] | None = None
) -> str:
    """渲染请求参数里的 ``{{key}}`` / ``{{page}}`` 模板。"""
    variables: dict[str, Any] = {
        "key": keyword,
        "keyword": keyword,
        "page": page,
        "page0": page - 1,
    }
    if extra:
        variables.update(extra)
    return text_parser.render_template(value, variables)


def _resolve(template: str, base: str, **extra: Any) -> str:
    """把请求地址模板解析成可用的绝对地址。

    规则：

    * 模板为空 → 用 ``base``（即调用方传入的那个地址）
    * 渲染后是绝对地址 → 原样使用
    * 否则 → 相对 ``base`` 拼接

    模板里可以用 ``{{bookUrl}}`` / ``{{chapterUrl}}`` 引用调用方传入的地址。
    """
    if not template.strip():
        return base
    rendered = _render(template, extra=extra).strip()
    if not rendered:
        return base
    if rendered.startswith(("http://", "https://")):
        return rendered
    return urljoin(base, rendered)


class NativeSourceAdapter(BaseSourceAdapter):
    """执行 YAML 原生书源。

    Args:
        source: 书源定义。
        spec: 已校验的原生书源规格。
        http: 可选的 HTTP 客户端，省略时按书源配置创建。
    """

    def __init__(
        self,
        source: BookSource,
        spec: NativeSourceSpec,
        http: HttpClient | None = None,
    ) -> None:
        super().__init__(source, http)
        self.spec = spec
        self._normalizer = ContentNormalizer(
            NormalizeRules(strip_selectors=list(spec.content.strip) if spec.content else [])
        )

    # -- 搜索 --------------------------------------------------------------

    async def search(self, keyword: str, page: int = 1) -> list[BookResult]:
        """搜索。未声明 search 能力的书源返回空列表。"""
        spec = self.spec.search
        if spec is None:
            return []

        url = spec.resolve_url(self.spec.url)
        params = {k: _render(v, keyword=keyword, page=page) for k, v in spec.params.items()}
        response = await self.http.request(
            spec.method,
            url,
            params=params or None,
            data={k: _render(v, keyword=keyword, page=page) for k, v in spec.data.items()} or None,
            headers=spec.headers or None,
        )
        if not response.ok:
            raise SourceError(
                f"搜索请求失败：HTTP {response.status}",
                code=ErrorCode.SEARCH_FAILED,
                details={"url": url, "status": response.status, "source_id": self.source.id},
            )

        doc = html_parser.parse_html(response.text, base_url=response.url)
        rows = spec.list.items(doc, response.url)

        results: list[BookResult] = []
        for row in rows:
            book_url = row.get("book_url")
            name = row.get("name")
            # 缺书名或详情页地址的条目直接丢弃 —— 它们无法被后续步骤使用
            if not name or not book_url:
                continue
            results.append(
                BookResult(
                    name=name,
                    author=row.get("author"),
                    intro=row.get("intro"),
                    cover_url=row.get("cover_url"),
                    category=row.get("category"),
                    status=row.get("status"),
                    latest_chapter=row.get("latest_chapter"),
                    book_url=book_url,
                )
            )
        return results

    # -- 详情 --------------------------------------------------------------

    async def book_info(self, book_url: str) -> BookResult:
        """获取书籍详情。未声明 book 能力时返回仅含地址的占位结果。"""
        spec = self.spec.book
        if spec is None:
            return BookResult(name="", book_url=book_url)

        target = _resolve(spec.url, book_url, bookUrl=book_url, book_url=book_url)
        response = await self.http.request(spec.method, target, headers=spec.headers or None)
        if not response.ok:
            raise SourceError(
                f"详情页请求失败：HTTP {response.status}",
                code=ErrorCode.SOURCE_EXECUTION_ERROR,
                details={"url": target, "status": response.status},
            )

        doc = html_parser.parse_html(response.text, base_url=response.url)
        values = {name: fs.extract(doc, response.url) for name, fs in spec.fields.items()}

        return BookResult(
            name=values.get("name") or "",
            author=values.get("author"),
            intro=values.get("intro"),
            cover_url=values.get("cover_url"),
            category=values.get("category"),
            status=values.get("status"),
            word_count=_as_int(values.get("word_count")),
            latest_chapter=values.get("latest_chapter"),
            book_url=book_url,
        )

    # -- 目录 --------------------------------------------------------------

    async def chapters(self, book_url: str) -> list[ChapterResult]:
        """获取目录，自动翻页。

        分页上限由 ``toc.max_pages`` 控制 —— 规则写错时必须能停下来，
        否则会陷入死循环（规划书 §22）。
        """
        spec = self.spec.toc
        if spec is None:
            return []

        current = _resolve(spec.url, book_url, bookUrl=book_url, book_url=book_url)

        chapters: list[ChapterResult] = []
        seen_urls: set[str] = set()

        for _ in range(spec.max_pages):
            response = await self.http.request(spec.method, current, headers=spec.headers or None)
            if not response.ok:
                raise SourceError(
                    f"目录页请求失败：HTTP {response.status}",
                    code=ErrorCode.CHAPTER_PARSE_FAILED,
                    details={"url": current, "status": response.status},
                )

            doc = html_parser.parse_html(response.text, base_url=response.url)
            for row in spec.list.items(doc, response.url):
                chapter_url = row.get("url")
                name = row.get("name")
                if not chapter_url or not name or chapter_url in seen_urls:
                    continue
                seen_urls.add(chapter_url)
                chapters.append(
                    ChapterResult(
                        index=len(chapters),
                        name=name,
                        url=chapter_url,
                        is_vip=_as_bool(row.get("is_vip")),
                    )
                )

            if not spec.next_page:
                break
            next_el = html_parser.select_one(doc, spec.next_page)
            next_href = next_el.get("href") if next_el is not None else None
            if not next_href:
                break
            current = urljoin(response.url, next_href)
            if current in seen_urls:  # 防御：下一页指回自己
                break

        return chapters

    # -- 正文 --------------------------------------------------------------

    async def content(self, chapter_url: str) -> ContentResult:
        """获取正文，自动拼接分页。"""
        spec = self.spec.content
        if spec is None:
            raise SourceError(
                "该书源未声明正文规则",
                code=ErrorCode.CONTENT_PARSE_FAILED,
                details={"source_id": self.source.id},
            )

        current = _resolve(spec.url, chapter_url, chapterUrl=chapter_url, chapter_url=chapter_url)
        parts: list[str] = []
        chapter_name: str | None = None
        images: list[str] = []
        visited: set[str] = set()

        for _ in range(spec.max_pages):
            if current in visited:
                break
            visited.add(current)

            response = await self.http.request(spec.method, current, headers=spec.headers or None)
            if not response.ok:
                raise SourceError(
                    f"正文页请求失败：HTTP {response.status}",
                    code=ErrorCode.CONTENT_PARSE_FAILED,
                    details={"url": current, "status": response.status},
                )

            doc = html_parser.parse_html(response.text, base_url=response.url)
            container = html_parser.select_one(doc, spec.selector)
            if container is None:
                raise SourceError(
                    "正文容器未匹配到内容，规则可能已失效",
                    code=ErrorCode.CONTENT_PARSE_FAILED,
                    details={"url": current, "selector": spec.selector},
                )

            # 先收图片地址，再剥离节点 —— 被规则剔除的节点里也可能有正文插图
            for img in container.xpath(".//img/@src"):
                images.append(urljoin(response.url, img))

            for strip_selector in spec.strip:
                html_parser.drop_elements(container, strip_selector)

            # 保留 HTML 片段交给 normalizer 处理：它才知道怎么剔除 script / 广告节点。
            # 在这里先转纯文本会把 script 内容直接混进正文。
            parts.append(html_parser.outer_html(container))

            if chapter_name is None:
                title = html_parser.text_of(doc, "h1")
                chapter_name = title

            if not spec.next_page:
                break
            next_el = html_parser.select_one(doc, spec.next_page)
            next_href = next_el.get("href") if next_el is not None else None
            if not next_href:
                break
            current = urljoin(response.url, next_href)

        raw = "\n".join(part for part in parts if part.strip())
        return ContentResult(
            content=self._normalizer.normalize(raw, is_html=True),
            raw=raw,
            chapter_name=chapter_name,
            images=images,
        )


def _as_int(value: str | None) -> int | None:
    """从「120万字」这类文本里提取数字。"""
    if not value:
        return None
    import re

    match = re.search(r"\d+", value.replace(",", ""))
    if match is None:
        return None
    number = int(match.group())
    # 「万字」单位换算
    if "万" in value:
        number *= 10000
    return number


def _as_bool(value: str | None) -> bool:
    """把常见的中文/英文布尔表示转成 bool。"""
    if not value:
        return False
    return value.strip().lower() in {"1", "true", "yes", "y", "是", "vip", "付费"}
