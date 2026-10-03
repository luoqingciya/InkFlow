"""Legado 书源适配器：执行编译后的规则 AST。

**兼容边界**：本模块实现 L0 + L1（JSON 结构 + CSS/XPath/JSONPath/正则）。
L2 的 ``@js:`` 规则在**启用 JS 运行时**（``[js] enabled = true``）时交给
Node sidecar 执行；未启用时抛 ``SOURCE_INVALID`` 并给出提示 ——
**失败要看得见**，不能返回空让调用方以为「这个字段本来就没有」。
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urljoin

from inkflow_js_runtime import JsRuntime, JsRuntimeError

from inkflow_core.errors import ErrorCode, SourceError
from inkflow_core.models import (
    BookResult,
    BookSource,
    ChapterResult,
    ContentResult,
)
from inkflow_legado.compiler import LegadoRuleCompiler, render_legado_template
from inkflow_legado.rules import Rule, RuleContext, RuleMode
from inkflow_legado.schema import LegadoBookSource
from inkflow_source.adapter import BaseSourceAdapter
from inkflow_source.http import HttpClient
from inkflow_source.normalizer import ContentNormalizer
from inkflow_source.parsers import html as html_parser

__all__ = ["LegadoSourceAdapter", "split_url_options"]


def split_url_options(text: str) -> tuple[str, dict[str, Any]]:
    """拆分 Legado 的 ``url,{json}`` 写法。

    Legado 允许在 URL 后面追加一段 JSON 来描述请求方法、请求体等：

        ``/search,{"method":"POST","body":"key={{key}}"}``
    """
    if "," not in text:
        return text, {}
    url, _, options = text.rpartition(",")
    options = options.strip()
    if not options.startswith("{"):
        return text, {}
    try:
        parsed = json.loads(options)
    except json.JSONDecodeError:
        return text, {}
    return url, parsed if isinstance(parsed, dict) else {}


class LegadoSourceAdapter(BaseSourceAdapter):
    """执行 Legado 书源。

    Args:
        source: 已入库的书源定义（``raw`` 中保存原始 Legado JSON）。
        definition: 解析后的 Legado 书源结构。
        http: 可选 HTTP 客户端。
    """

    def __init__(
        self,
        source: BookSource,
        definition: LegadoBookSource,
        http: HttpClient | None = None,
        js: JsRuntime | None = None,
    ) -> None:
        super().__init__(source, http)
        self.definition = definition
        self.js = js
        self.compiler = LegadoRuleCompiler()
        self._normalizer = ContentNormalizer()

        #: 书源级变量（``java.put`` / ``java.get``）。生命周期跟着 adapter 走 ——
        #: 书源常用它把 tocUrl 里算出的 bookId 传给 chapterUrl。
        #: 注意别跟下面那个 ``_variables()`` **方法**（模板变量）重名。
        self._js_variables: dict[str, str] = {}
        #: 当前 JS 规则的求值上下文。``java.getString`` 靠它取值。
        self._current_context: RuleContext | None = None
        #: 单次规则执行的**网络**请求上限（来自 ``[js]`` 段；0 = 不限制）。
        self._js_request_limit: int = js.config.max_requests if js is not None else 0
        #: 本次求值已发起的网络请求数。计数在 ``_host_fetch``，重置在 ``_eval_js``。
        self._js_request_count: int = 0

        # 预编译规则：编译一次，多次执行
        self._rule_search_list = self.compiler.compile(definition.ruleSearch.bookList)
        self._rule_search_fields = self.compiler.compile_many(
            {
                "name": definition.ruleSearch.name,
                "author": definition.ruleSearch.author,
                "intro": definition.ruleSearch.intro,
                "cover_url": definition.ruleSearch.coverUrl,
                "book_url": definition.ruleSearch.bookUrl,
                "category": definition.ruleSearch.kind,
                "latest_chapter": definition.ruleSearch.lastChapter,
                "word_count": definition.ruleSearch.wordCount,
            }
        )
        self._rule_book_fields = self.compiler.compile_many(
            {
                "name": definition.ruleBookInfo.name,
                "author": definition.ruleBookInfo.author,
                "intro": definition.ruleBookInfo.intro,
                "cover_url": definition.ruleBookInfo.coverUrl,
                "category": definition.ruleBookInfo.kind,
                "latest_chapter": definition.ruleBookInfo.lastChapter,
                "word_count": definition.ruleBookInfo.wordCount,
            }
        )
        self._rule_toc_url = self.compiler.compile_optional(definition.ruleBookInfo.tocUrl)
        self._rule_toc_list = self.compiler.compile(definition.ruleToc.chapterList)
        self._rule_toc_fields = self.compiler.compile_many(
            {
                "name": definition.ruleToc.chapterName,
                "url": definition.ruleToc.chapterUrl,
                "is_vip": definition.ruleToc.isVip,
            }
        )
        self._rule_toc_next = self.compiler.compile_optional(definition.ruleToc.nextTocUrl)
        self._rule_content = self.compiler.compile(definition.ruleContent.content)
        self._rule_content_next = self.compiler.compile_optional(
            definition.ruleContent.nextContentUrl
        )

    @classmethod
    def from_source(
        cls,
        source: BookSource,
        http: HttpClient | None = None,
        js: JsRuntime | None = None,
    ) -> LegadoSourceAdapter:
        """从已入库的书源定义构建适配器。

        Args:
            source: 书源定义。
            http: 由注册表注入的 HTTP 客户端；省略时按书源配置惰性创建。
            js: 共享的 JS 运行时（``[js] enabled = true`` 时由装配层注入）。
        """
        try:
            definition = LegadoBookSource.model_validate(source.raw)
        except Exception as exc:
            raise SourceError(
                f"Legado 书源结构校验失败：{exc}",
                code=ErrorCode.SOURCE_INVALID,
                details={"source_id": source.id},
            ) from exc
        return cls(source, definition, http, js)

    # -- 请求辅助 ----------------------------------------------------------

    def _variables(self, **extra: Any) -> dict[str, Any]:
        """构造模板变量表。"""
        variables: dict[str, Any] = {
            "baseUrl": self.definition.bookSourceUrl,
            "key": "",
            "keyword": "",
            "page": 1,
            "page0": 0,
        }
        variables.update(extra)
        return variables

    def _resolve_url(self, template: str, **extra: Any) -> str:
        """渲染 URL 模板并转绝对地址。"""
        rendered = render_legado_template(template, self._variables(**extra)).strip()
        return urljoin(self.definition.bookSourceUrl, rendered)

    def _guard_js(self, rule: Rule, where: str) -> None:
        """遇到 JS 规则时抛出明确错误，而不是返回空结果。

        MVP 只覆盖 L0 + L1；静默失败会让用户以为「书源坏了」，
        而实际上只是兼容等级没到。
        """
        if rule.needs_js:
            raise SourceError(
                f"{where} 规则包含 JavaScript，需要 L2 兼容等级（当前版本未实现）",
                code=ErrorCode.SOURCE_EXECUTION_ERROR,
                details={"source_id": self.source.id, "rule": rule.raw, "required_level": "L2"},
            )

    async def _fetch(
        self,
        url_template: str,
        *,
        method: str | None = None,
        data: Any = None,
        **variables: Any,
    ) -> tuple[str, Any]:
        """请求并解析页面，返回 ``(html_text, doc)``。

        Returns:
            正文文本与解析后的 DOM。
        """
        url, options = split_url_options(url_template)
        resolved = self._resolve_url(url, **variables)
        http_method = method or str(options.get("method", "GET")).upper()

        body = data if data is not None else options.get("body")
        if isinstance(body, str):
            body = render_legado_template(body, self._variables(**variables))

        headers = dict(self.definition.headers)
        if isinstance(options.get("headers"), dict):
            headers.update({str(k): str(v) for k, v in options["headers"].items()})

        if http_method == "POST":
            response = await self.http.post(resolved, data=body, headers=headers or None)
        else:
            response = await self.http.get(resolved, headers=headers or None)

        if not response.ok:
            raise SourceError(
                f"请求失败：HTTP {response.status}",
                code=ErrorCode.SOURCE_EXECUTION_ERROR,
                details={
                    "url": resolved,
                    "status": response.status,
                    "source_id": self.source.id,
                },
            )
        doc = html_parser.parse_html(response.text, base_url=response.url)
        return response.text, doc

    # -- 搜索 --------------------------------------------------------------

    async def search(self, keyword: str, page: int = 1) -> list[BookResult]:
        """搜索。"""
        if not self.definition.search_enabled:
            return []
        self._guard_js(self._rule_search_list, "搜索列表")

        _, doc = await self._fetch(
            self.definition.searchUrl, key=keyword, keyword=keyword, page=page
        )
        context_base = RuleContext(doc=doc, base_url=self.definition.bookSourceUrl)

        results: list[BookResult] = []
        for node in self._rule_search_list.select_nodes(doc):
            context = RuleContext(
                doc=node, base_url=getattr(doc, "base_url", "") or self.definition.bookSourceUrl
            )
            name = (
                self._rule_search_fields["name"].evaluate_one(context)
                if "name" in self._rule_search_fields
                else None
            )
            book_url = (
                self._rule_search_fields["book_url"].evaluate_one(context)
                if "book_url" in self._rule_search_fields
                else None
            )
            if not name or not book_url:
                continue

            results.append(
                BookResult(
                    name=name,
                    author=await self._field(self._rule_search_fields, "author", context),
                    intro=await self._field(self._rule_search_fields, "intro", context),
                    cover_url=await self._field(self._rule_search_fields, "cover_url", context),
                    category=await self._field(self._rule_search_fields, "category", context),
                    latest_chapter=await self._field(
                        self._rule_search_fields, "latest_chapter", context
                    ),
                    book_url=book_url,
                )
            )
        _ = context_base  # 保留上下文构造，便于后续支持 init 规则
        return results

    # -- 详情 --------------------------------------------------------------

    async def book_info(self, book_url: str) -> BookResult:
        """获取详情。"""
        _, doc = await self._fetch(book_url, bookUrl=book_url)
        context = RuleContext(doc=doc, base_url=book_url)

        return BookResult(
            name=await self._field(self._rule_book_fields, "name", context) or "",
            author=await self._field(self._rule_book_fields, "author", context),
            intro=await self._field(self._rule_book_fields, "intro", context),
            cover_url=await self._field(self._rule_book_fields, "cover_url", context),
            category=await self._field(self._rule_book_fields, "category", context),
            latest_chapter=await self._field(self._rule_book_fields, "latest_chapter", context),
            word_count=_to_int(await self._field(self._rule_book_fields, "word_count", context)),
            book_url=book_url,
        )

    # -- 目录 --------------------------------------------------------------

    async def chapters(self, book_url: str) -> list[ChapterResult]:
        """获取目录，支持 ``nextTocUrl`` 翻页。"""
        toc_url = book_url
        if self._rule_toc_url is not None:
            _, doc = await self._fetch(book_url, bookUrl=book_url)
            resolved = self._rule_toc_url.evaluate_one(RuleContext(doc=doc, base_url=book_url))
            if resolved:
                toc_url = resolved

        chapters: list[ChapterResult] = []
        seen: set[str] = set()
        current = toc_url
        max_pages = 50  # 防御性上限：规则写错时必须能停下来

        for _ in range(max_pages):
            if current in seen:
                break
            seen.add(current)

            _, doc = await self._fetch(current, bookUrl=book_url)
            base_url = current

            for node in self._rule_toc_list.select_nodes(doc):
                context = RuleContext(doc=node, base_url=base_url)
                name = await self._field(self._rule_toc_fields, "name", context)
                url = await self._field(self._rule_toc_fields, "url", context)
                if not name or not url or url in {c.url for c in chapters}:
                    continue
                chapters.append(
                    ChapterResult(
                        index=len(chapters),
                        name=name,
                        url=url,
                        is_vip=_to_bool(
                            await self._field(self._rule_toc_fields, "is_vip", context)
                        ),
                    )
                )

            if self._rule_toc_next is None:
                break
            next_url = self._rule_toc_next.evaluate_one(RuleContext(doc=doc, base_url=base_url))
            if not next_url:
                break
            current = next_url

        return chapters

    # -- 正文 --------------------------------------------------------------

    async def content(self, chapter_url: str) -> ContentResult:
        """获取正文，支持 ``nextContentUrl`` 分页拼接。"""
        self._guard_js(self._rule_content, "正文")

        parts: list[str] = []
        chapter_name: str | None = None
        current = chapter_url
        visited: set[str] = set()

        for _ in range(50):
            if current in visited:
                break
            visited.add(current)

            _, doc = await self._fetch(current, chapterUrl=current)
            context = RuleContext(doc=doc, base_url=current)

            value = self._rule_content.evaluate_one(context)
            if not value:
                raise SourceError(
                    "正文规则未匹配到内容，书源规则可能已失效",
                    code=ErrorCode.CONTENT_PARSE_FAILED,
                    details={
                        "url": current,
                        "source_id": self.source.id,
                        "rule": self._rule_content.raw,
                    },
                )
            parts.append(value)

            if chapter_name is None:
                chapter_name = html_parser.text_of(doc, "h1")

            if self._rule_content_next is None:
                break
            next_url = self._rule_content_next.evaluate_one(context)
            if not next_url:
                break
            current = next_url

        raw = "\n".join(parts)
        return ContentResult(
            content=self._normalizer.normalize(raw, is_html=True),
            raw=raw,
            chapter_name=chapter_name,
        )

    # -- 内部 --------------------------------------------------------------

    async def _field(self, rules: dict[str, Rule], name: str, context: RuleContext) -> str | None:
        """取某个字段的值；规则缺失时返回 ``None``。

        ``@js:`` 规则要跑 Node sidecar，所以这里是异步的 —— 其余模式
        仍是同步求值，只是被包在同一个入口里。
        """
        rule = rules.get(name)
        if rule is None:
            return None
        if rule.mode is RuleMode.JS:
            return await self._eval_js(rule, context)
        return rule.evaluate_one(context)

    async def _eval_js(self, rule: Rule, context: RuleContext) -> str | None:
        """执行 ``@js:`` 规则。

        Raises:
            SourceError: 未启用 JS 运行时，或执行失败。
                未启用时**明确报错**而不是返回空 —— 返回空会让调用方以为
                「这个字段本来就没有」，把配置问题伪装成解析问题。
        """
        if self.js is None:
            # 解法写进 message 而不是只放 details —— 用户看到的是 message，
            # 只说「未启用」而不说「怎么启用」等于没帮上忙。
            raise SourceError(
                f"规则需要 JS 运行时，但未启用：{rule.raw[:120]}\n"
                f"在 config.toml 的 [js] 段设置 enabled = true 后重启服务。",
                code=ErrorCode.SOURCE_INVALID,
                details={
                    "rule": rule.raw[:200],
                    "hint": "config.toml 的 [js] 段设置 enabled = true",
                },
            )

        code = rule.code or ""
        if not code:
            return None

        variables = {
            "baseUrl": context.base_url,
            "result": context.data,
        }

        # 记下上下文与请求计数：java.getString 要拿上下文求值，
        # max_requests 按单次求值计数。
        # 用 try/finally 还原 —— 嵌套调用（规则里再触发规则）时不能串味。
        previous_context = self._current_context
        previous_count = self._js_request_count
        self._current_context = context
        self._js_request_count = 0
        try:
            value = await self.js.eval(
                code,
                variables=variables,
                host_request=self._host_request,
            )
        except JsRuntimeError as exc:
            raise SourceError(
                f"JS 规则执行失败（{exc.kind}）：{exc}",
                code=ErrorCode.CONTENT_PARSE_FAILED,
                details={"rule": rule.raw[:200], "kind": exc.kind},
            ) from exc
        finally:
            self._current_context = previous_context
            self._js_request_count = previous_count

        return None if value is None else str(value)

    async def _host_request(self, params: dict[str, Any]) -> dict[str, Any]:
        """处理 sidecar 回调的宿主请求。

        三类：

        - ``getString`` —— 用规则从**当前上下文**取值（复用 Python 的求值能力）
        - ``put`` / ``get`` —— 书源级变量
        - 其余 —— 网络请求（``java.ajax``）
        """
        op = params.get("op")
        if op == "getString":
            return self._host_get_string(params)
        if op == "put":
            key = str(params.get("key", ""))
            value = params.get("value")
            self._js_variables[key] = "" if value is None else str(value)
            return {"ok": True, "value": self._js_variables[key]}
        if op == "get":
            key = str(params.get("key", ""))
            return {"ok": True, "value": self._js_variables.get(key, "")}

        return await self._host_fetch(params)

    def _host_get_string(self, params: dict[str, Any]) -> dict[str, Any]:
        """``java.getString(rule)`` —— 用规则在当前上下文取值。

        复用编译器的求值能力（含 ``!N`` 下标、隐式 JSONPath 等），
        而不是在 JS 侧重造一套 —— 两套实现迟早会不一致。
        """
        context = self._current_context
        if context is None:
            return {"ok": False, "error": "没有可用的取值上下文"}

        rule_text = str(params.get("rule", ""))
        # Legado 的第二个参数传 false 表示「按字面量处理，不解析成规则」
        if params.get("isRule") is False:
            return {"ok": True, "value": rule_text}

        try:
            rule = self.compiler.compile(rule_text)
            values = rule.evaluate(context)
        except Exception as exc:
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

        # Legado 的 getString 返回单值，多条时取第一条
        return {"ok": True, "value": values[0] if values else ""}

    async def _host_fetch(self, params: dict[str, Any]) -> dict[str, Any]:
        """``java.ajax`` 一类网络请求。

        请求回到这里发出，而不是让 sidecar 自己联网 —— 这样 SSRF 防护、
        协议白名单、限速、缓存全部照旧生效。
        """
        # 上限按「单次规则执行」计，只数网络请求 —— java.getString / put / get
        # 是本地操作，不算在内（否则上限会被取值调用提前触发）。
        limit = self._js_request_limit
        if limit and self._js_request_count >= limit:
            return {
                "ok": False,
                "error": (
                    f"单次规则执行的网络请求超过上限（{limit} 次）。"
                    f"确实需要更多请求的话，调大 config.toml 的 [js] max_requests。"
                ),
            }
        self._js_request_count += 1

        if self.http is None:
            return {"ok": False, "error": "该书源没有 HTTP 客户端"}

        url = str(params.get("url", ""))
        method = str(params.get("method", "GET")).upper()
        body = params.get("body")
        headers = params.get("headers") or None

        try:
            response = await self.http.request(method, url, data=body, headers=headers)
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

        if not response.ok:
            return {"ok": False, "error": f"HTTP {response.status}"}

        return {"ok": True, "body": response.text}


def _to_int(value: str | None) -> int | None:
    """从「120万字」这类文本里提取数字。"""
    if not value:
        return None
    import re

    match = re.search(r"\d+", value.replace(",", ""))
    if match is None:
        return None
    number = int(match.group())
    if "万" in value:
        number *= 10000
    return number


def _to_bool(value: str | None) -> bool:
    """把常见布尔表示转成 bool。"""
    if not value:
        return False
    return value.strip().lower() in {"1", "true", "yes", "y", "是", "vip", "付费"}
