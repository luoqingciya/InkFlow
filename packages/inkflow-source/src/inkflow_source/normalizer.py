"""正文标准化（规划书 §18）。

网页正文 → 标准正文的转换管线：

    网页正文
      ↓  移除指定 DOM 节点
      ↓  DOM → 文本（保留段落）
      ↓  逐行清理（零宽字符、首尾空白）
      ↓  广告 / 推广行剔除
      ↓  重复段落合并
      ↓  空行规范化
      ↓  首尾噪声裁剪
    标准正文

``raw_content`` 始终保留在 ``ChapterContent`` 中，因此**改清洗规则不需要
重新抓取**，只需对已有原始数据重跑本管线。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from lxml.html import HtmlElement

from inkflow_source.parsers import html as html_parser

__all__ = ["DEFAULT_RULES", "ContentNormalizer", "NormalizeRules"]


#: 默认广告 / 推广行模式。
#: 全部锚定整行且要求行内无句读，避免误伤正文里的正常句子。
DEFAULT_AD_PATTERNS: tuple[str, ...] = (
    r"^本章未完[，,]?\s*请?点击下一页继续阅读.*$",
    r"^请记住本站[^。！？]{0,40}$",
    r"^请记住本书[^。！？]{0,40}$",
    r"^(?:手机|移动)用户请[^。！？]{0,40}$",
    r"^(?:最新|最快)(?:网址|更新)[：:][^。！？]{0,60}$",
    r"^一秒记住[^。！？]{0,40}$",
    r"^(?:天才|神级)?一秒记住本站[^。！？]{0,40}$",
    r"^无弹窗[^。！？]{0,40}$",
    r"^(?:全文|免费)阅读[^。！？]{0,40}$",
    r"^[『【\[]?(?:加入)?(?:书签|书架)[』】\]]?[，,]?方便阅读.*$",
    r"^(?:投|求)(?:推荐票|月票|收藏|订阅|打赏)[^。！？]{0,30}$",
    r"^\s*(?:www|m|wap)\.[\w\-.]+\s*$",
    r"^\s*https?://\S+\s*$",
    r"^[（(]\s*本章完\s*[)）]\s*$",
    r"^\s*[（(]\s*\d+\s*[)）]\s*页\s*$",
    r"^笔趣阁[^。！？]{0,30}$",
    r"^.{0,10}(?:小说网|文学网|阅读网)\s*$",
)

#: 默认整块移除的节点。
#: 前一组是结构性噪声（不可能属于正文）；后一组是明确标注为广告的类名 / id，
#: 写法刻意保守 —— 宽泛的 ``[class*=ad]`` 会误伤 "read"、"head" 这类正常类名。
DEFAULT_STRIP_SELECTORS: tuple[str, ...] = (
    "script",
    "style",
    "noscript",
    "iframe",
    "svg",
    ".ad",
    ".ads",
    ".advert",
    ".advertisement",
    ".ad-inline",
    ".ad-container",
    "[class^='ad-']",
    "[id^='ad-']",
)

#: 章节首尾噪声：重复出现的章节标题行、分隔符
DEFAULT_NOISE_PATTERNS: tuple[str, ...] = (
    r"^\s*[-=—=*·]{3,}\s*$",
    r"^\s*[（(]?未完待续[)）]?\s*$",
)

#: 零宽与不可见字符
_INVISIBLE_RE = re.compile(r"[\u200b-\u200f\u2028-\u202f\ufeff\xa0]")


@dataclass(slots=True)
class NormalizeRules:
    """清洗规则。

    Attributes:
        strip_selectors: 需要整块移除的 CSS 选择器 / XPath。
        ad_patterns: 整行匹配即丢弃的正则。
        noise_patterns: 首尾噪声正则。
        dedupe_paragraphs: 是否合并重复段落。
        dedupe_min_length: 参与去重的最短行长度，太短的行（如「……」）不参与。
        dedupe_max_repeat: 允许的最大重复次数，超出才判定为噪声。
        max_consecutive_blank: 连续空行上限。
        trim_edges: 是否裁剪首尾噪声行。
        normalize_fullwidth: 是否把全角字母数字折成半角（默认否，正文标点应保留）。
    """

    #: 追加到 DEFAULT_STRIP_SELECTORS 之后的移除规则
    strip_selectors: list[str] = field(default_factory=list)
    ad_patterns: list[str] = field(default_factory=list)
    noise_patterns: list[str] = field(default_factory=list)
    dedupe_paragraphs: bool = True
    dedupe_min_length: int = 8
    dedupe_max_repeat: int = 2
    max_consecutive_blank: int = 1
    trim_edges: bool = True
    normalize_fullwidth: bool = False

    def compiled_strip_selectors(self) -> list[str]:
        """默认移除规则 + 书源自定义规则。"""
        return list(DEFAULT_STRIP_SELECTORS) + self.strip_selectors

    def compiled_ads(self) -> list[re.Pattern[str]]:
        patterns = list(DEFAULT_AD_PATTERNS) + self.ad_patterns
        return [re.compile(p) for p in patterns]

    def compiled_noise(self) -> list[re.Pattern[str]]:
        patterns = list(DEFAULT_NOISE_PATTERNS) + self.noise_patterns
        return [re.compile(p) for p in patterns]


DEFAULT_RULES = NormalizeRules()

_FULLWIDTH_MAP = str.maketrans(
    "０１２３４５６７８９ＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＱＲＳＴＵＶＷＸＹＺ"
    "ａｂｃｄｅｆｇｈｉｊｋｌｍｎｏｐｑｒｓｔｕｖｗｘｙｚ",
    "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz",
)


class ContentNormalizer:
    """正文清洗器。

    Args:
        rules: 清洗规则；省略时使用默认规则。
    """

    def __init__(self, rules: NormalizeRules | None = None) -> None:
        self.rules = rules or DEFAULT_RULES

    # -- 对外入口 ----------------------------------------------------------

    def normalize(self, raw: str, *, is_html: bool = True) -> str:
        """把原始正文转成标准正文。

        Args:
            raw: 原始正文，可能是 HTML 片段或纯文本。
            is_html: 为 ``True`` 时先走 DOM 处理。
        """
        if not raw or not raw.strip():
            return ""

        text = self._extract_text(raw) if is_html else raw
        return self.clean_text(text)

    def clean_text(self, text: str) -> str:
        """对纯文本执行清洗（不做 DOM 处理）。"""
        lines = self._split_lines(text)
        lines = self._drop_ads(lines)
        if self.rules.dedupe_paragraphs:
            lines = self._dedupe(lines)
        lines = self._collapse_blanks(lines)
        if self.rules.trim_edges:
            lines = self._trim_noise(lines)
        result = "\n".join(lines).strip()
        if self.rules.normalize_fullwidth:
            result = result.translate(_FULLWIDTH_MAP)
        return result

    # -- 内部步骤 ----------------------------------------------------------

    def _extract_text(self, raw: str) -> str:
        """HTML → 保留段落的文本。

        先按选择器移除节点再抽文本 —— 顺序反了会把广告文字留在正文里。
        """
        doc: HtmlElement = html_parser.parse_html(raw)
        for selector in self.rules.compiled_strip_selectors():
            html_parser.drop_elements(doc, selector)
        return html_parser.element_to_text(doc)

    @staticmethod
    def _split_lines(text: str) -> list[str]:
        """拆行并清理不可见字符与首尾空白。"""
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        text = _INVISIBLE_RE.sub("", text)
        return [line.strip() for line in text.split("\n")]

    def _drop_ads(self, lines: list[str]) -> list[str]:
        """剔除广告 / 推广行。"""
        patterns = self.rules.compiled_ads()
        return [line for line in lines if not any(p.match(line) for p in patterns)]

    def _dedupe(self, lines: list[str]) -> list[str]:
        """合并重复段落。

        只处理**足够长**且重复次数超过阈值的行 —— 小说正文里出现两次
        「……」，或两次「好。」都是正常的，不该被删。
        """
        counts: dict[str, int] = {}
        for line in lines:
            if len(line) >= self.rules.dedupe_min_length:
                counts[line] = counts.get(line, 0) + 1

        result: list[str] = []
        emitted: set[str] = set()
        for line in lines:
            if len(line) >= self.rules.dedupe_min_length:
                count = counts.get(line, 0)
                if count > self.rules.dedupe_max_repeat:
                    if line in emitted:
                        continue
                    emitted.add(line)
            result.append(line)
        return result

    def _collapse_blanks(self, lines: list[str]) -> list[str]:
        """把连续空行压到上限。"""
        result: list[str] = []
        blanks = 0
        for line in lines:
            if line:
                blanks = 0
                result.append(line)
            else:
                blanks += 1
                if blanks <= self.rules.max_consecutive_blank:
                    result.append("")
        return result

    def _trim_noise(self, lines: list[str]) -> list[str]:
        """裁剪首尾的噪声行（分隔符、重复标题、页脚）。"""
        patterns = self.rules.compiled_noise()

        def is_noise(line: str) -> bool:
            return not line or any(p.match(line) for p in patterns)

        start = 0
        while start < len(lines) and is_noise(lines[start]):
            start += 1
        end = len(lines)
        while end > start and is_noise(lines[end - 1]):
            end -= 1
        return lines[start:end]
