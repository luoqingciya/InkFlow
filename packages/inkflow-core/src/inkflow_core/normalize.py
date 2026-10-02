"""文本归一化与哈希。

这里只做**与业务无关的机械归一化**（宽度、空白、大小写），
用于书籍去重与缓存键计算。真正的正文清洗属于 ContentNormalizer 的职责，
不在此模块内。
"""

from __future__ import annotations

import hashlib
import re
import unicodedata

__all__ = [
    "content_hash",
    "hash_bytes",
    "normalize_author",
    "normalize_book_name",
    "normalize_text",
]

# 归一化时丢弃的字符：空白、常见中英文标点、装饰性符号
_PUNCT_RE = re.compile(
    r"[\s\u3000"
    r"!-/:-@\[-`{-~"
    r"\u2010-\u2027\u2030-\u205e"
    r"\u3001-\u303f\uff01-\uff0f\uff1a-\uff20\uff3b-\uff40\uff5b-\uff65"
    r"]+"
)


def normalize_text(value: str) -> str:
    """NFKC 归一化 + 折叠空白 + 转小写。

    NFKC 会把全角字母数字、罗马数字、带圈字符等折叠成标准形式，
    因此 ``"三体Ⅲ"`` 与 ``"三体III"`` 在此步后一致。
    """
    text = unicodedata.normalize("NFKC", value)
    text = text.replace("\u3000", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip().lower()


def normalize_book_name(value: str) -> str:
    """书名归一化：在 ``normalize_text`` 基础上再剥离标点与空白。

    用于跨书源识别同一本书，例如 ``《斗破苍穹》`` 与 ``斗破苍穹 第1部``
    归一化后得到可比较的键。
    """
    return _PUNCT_RE.sub("", normalize_text(value))


def normalize_author(value: str | None) -> str:
    """作者名归一化。``None`` 视为空串，避免调用方到处判空。"""
    if not value:
        return ""
    return _PUNCT_RE.sub("", normalize_text(value))


def hash_bytes(data: bytes) -> str:
    """返回字节内容的 SHA256 十六进制摘要。"""
    return hashlib.sha256(data).hexdigest()


def content_hash(text: str, *, encoding: str = "utf-8") -> str:
    """返回文本内容的 SHA256 摘要，用作缓存键与变更检测。

    先做 ``normalize_text`` 再哈希，使仅空白差异的两个版本命中同一缓存。
    """
    return hash_bytes(normalize_text(text).encode(encoding))
