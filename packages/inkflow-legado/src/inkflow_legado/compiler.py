"""Legado 规则编译器：DSL → 统一 AST。

Legado 规则字符串的语法（依据公开的规则格式独立实现）：

    [选择器链] @ [取值动作] ## [正则] ## [替换] ## ...

选择器写法：

    class.xxx       →  .xxx
    tag.a           →  a
    id.xxx          →  #xxx
    class.a.tag.b   →  .a b        （逐级下钻）
    @css:...        强制 CSS
    @XPath:...      强制 XPath
    @json:$.a.b     JSONPath
    @js:...         JavaScript（L2，MVP 阶段不支持执行）

多条规则用 ``||`` 分隔，取第一个有结果的。
"""

from __future__ import annotations

import re

from inkflow_legado.rules import Replacement, Rule, RuleMode
from inkflow_source.parsers import text as text_parser

__all__ = ["LegadoRuleCompiler", "compile_rule", "legado_selector_to_css"]

#: 强制模式前缀
_MODE_PREFIXES: tuple[tuple[str, RuleMode], ...] = (
    ("@css:", RuleMode.CSS),
    ("@CSS:", RuleMode.CSS),
    ("@xpath:", RuleMode.XPATH),
    ("@XPath:", RuleMode.XPATH),
    ("@XPATH:", RuleMode.XPATH),
    ("@json:", RuleMode.JSON),
    ("@JSON:", RuleMode.JSON),
    ("@js:", RuleMode.JS),
    ("@JS:", RuleMode.JS),
)

#: 明确的取值动作
_EXTRACT_ACTIONS = frozenset(
    {
        "text",
        "textNodes",
        "ownText",
        "html",
        "all",
        "outerHtml",
        "innerHtml",
        "href",
        "src",
        "content",
        "value",
        "title",
        "alt",
        "data-src",
        "data-original",
    }
)

#: 合法属性名（无点、无选择器特征）
_ATTR_NAME_RE = re.compile(r"^[A-Za-z_][\w-]*$")

#: XPath 末尾的属性 / 文本取值
_XPATH_TAIL_RE = re.compile(r"^(?P<path>.+?)/(?P<tail>@[\w:-]+|text\(\))$")


def legado_selector_to_css(selector: str) -> str:
    """把 Legado 选择器写法转成标准 CSS / XPath。

    已经是标准写法的原样返回。
    """
    value = selector.strip()
    if not value:
        return ""
    if value.startswith(("/", "(", ".", "#", "[")):
        return value

    match = re.match(r"^(class|tag|id)\.(.+)$", value, re.IGNORECASE)
    if match is None:
        return value

    kind = match.group(1).lower()
    rest = match.group(2)
    if kind == "class":
        return f".{rest}"
    if kind == "id":
        return f"#{rest}"
    return rest  # tag


def _parse_replacements(text: str) -> list[Replacement]:
    """解析 ``pattern##replacement`` 序列。"""
    if not text:
        return []
    parts = text.split("##")
    replacements: list[Replacement] = []
    for index in range(0, len(parts) - 1, 2):
        pattern = parts[index]
        if not pattern:
            continue
        replacements.append(Replacement(pattern=pattern, replacement=parts[index + 1]))
    return replacements


def _strip_mode_prefix(text: str) -> tuple[str, RuleMode | None]:
    """剥离 ``@css:`` / ``@XPath:`` / ``@json:`` 前缀。"""
    for prefix, mode in _MODE_PREFIXES:
        if text.startswith(prefix):
            return text[len(prefix) :], mode
    return text, None


def _parse_single(text: str) -> Rule:
    """编译**一条**（不含 ``||``）规则。"""
    raw = text.strip()
    if not raw:
        return Rule(raw=raw)

    # 1. 先切出 ## 替换部分 —— 正则里可能含 @ 或 |，必须先隔离
    split_at = raw.find("##")
    if split_at >= 0:
        body = raw[:split_at]
        replacement_text = raw[split_at + 2 :]
    else:
        body = raw
        replacement_text = ""

    # 2. 剥离模式前缀
    body, forced_mode = _strip_mode_prefix(body.strip())
    replacements = _parse_replacements(replacement_text)

    # 3. 强制 JS 模式：编译成功，执行与否由运行时决定
    if forced_mode is RuleMode.JS:
        # 存剥离后的代码：``raw`` 带着 ``@js:`` 前缀，直接喂给 JS 引擎会语法错误
        return Rule(raw=raw, mode=RuleMode.JS, code=body.strip(), replacements=replacements)

    # 4. JSON 模式：整段是 JSONPath
    if forced_mode is RuleMode.JSON:
        return Rule(
            raw=raw,
            mode=RuleMode.JSON,
            json_path=body.strip(),
            replacements=replacements,
        )

    # 5. XPath 模式：整段是 XPath，末尾可能是 @attr / text()
    if forced_mode is RuleMode.XPATH or body.strip().startswith(("/", "(")):
        path = body.strip()
        extract = "text"
        if match := _XPATH_TAIL_RE.match(path):
            path = match.group("path")
            tail = match.group("tail")
            extract = "text" if tail == "text()" else tail[1:]
        return Rule(
            raw=raw,
            mode=RuleMode.XPATH,
            selectors=[path],
            extract=extract,
            replacements=replacements,
        )

    # 6. CSS 模式：按 @ 切分选择器链与取值动作
    parts = [part for part in body.split("@") if part.strip()]
    if not parts:
        return Rule(raw=raw, mode=RuleMode.CSS, replacements=replacements)

    # 取值动作的识别：
    # * 只有一段时，仅当它是明确的取值动作（`text` / `href` 等）才算 —— 这种写法
    #   表示「作用于元素自身」，在 chapterName / chapterUrl 里非常常见；
    # * 有多段时，末段只要长得像属性名就算，因为选择器不会写成裸单词。
    extract = "text"
    if parts:
        last = parts[-1].strip()
        is_action = last in _EXTRACT_ACTIONS or (
            len(parts) > 1
            and _ATTR_NAME_RE.match(last) is not None
            and not last.startswith(("class", "tag", "id"))
        )
        if is_action:
            extract = last
            parts = parts[:-1]

    selectors = [css for css in (legado_selector_to_css(p) for p in parts) if css]
    return Rule(
        raw=raw,
        mode=RuleMode.CSS,
        selectors=selectors,
        extract=extract,
        replacements=replacements,
    )


def _split_fallbacks(text: str) -> list[str]:
    """按顶层 ``||`` 切分备选规则。"""
    if "##" in text:
        head, _, tail = text.partition("##")
        # 替换段里的 | 不参与切分
        return [part for part in head.split("||") if part.strip()] + [f"##{tail}"]
    return [part for part in text.split("||") if part.strip()]


class LegadoRuleCompiler:
    """把 Legado 规则字符串编译为 ``Rule``。"""

    def compile(self, text: str | None) -> Rule:
        """编译规则；``None`` / 空串返回空规则。"""
        if not text or not text.strip():
            return Rule(raw="")

        segments = _split_fallbacks(text)
        if not segments:
            return Rule(raw=text)

        rules = [_parse_single(segment) for segment in segments]
        # 把 ## 替换段回填到主规则（_split_fallbacks 会把它单独切出来）
        primary = rules[0]
        for extra in rules[1:]:
            if extra.raw.startswith("##"):
                primary.replacements.extend(_parse_replacements(extra.raw[2:]))
            else:
                primary.fallbacks.append(extra)
        return primary

    def compile_optional(self, text: str | None) -> Rule | None:
        """编译规则；空规则返回 ``None``，便于调用方判断「未配置」。"""
        rule = self.compile(text)
        return None if rule.is_empty else rule

    def compile_many(self, rules: dict[str, str | None]) -> dict[str, Rule]:
        """批量编译字段规则字典，跳过空规则。"""
        compiled: dict[str, Rule] = {}
        for name, text in rules.items():
            rule = self.compile_optional(text)
            if rule is not None:
                compiled[name] = rule
        return compiled


#: 无状态，可安全复用
default_compiler = LegadoRuleCompiler()


def compile_rule(text: str | None) -> Rule:
    """便捷入口。"""
    return default_compiler.compile(text)


def render_legado_template(template: str, variables: dict[str, object]) -> str:
    """渲染 Legado URL 模板。

    Legado 用 ``{{key}}`` 占位，另有一批内置变量（``{{page}}`` 等）。
    """
    return text_parser.render_template(template, variables)
