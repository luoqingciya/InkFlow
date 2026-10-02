"""领域模型测试。"""

from __future__ import annotations

import pytest

from inkflow_core.errors import TaskError
from inkflow_core.models import (
    Book,
    BookSource,
    ChapterContent,
    CompatibilityLevel,
    DownloadTask,
    SourceFormat,
    SourceType,
    TaskStatus,
    can_transition,
)
from inkflow_core.normalize import normalize_author, normalize_book_name, normalize_text

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------- 归一化


def test_normalize_text_folds_width_and_case() -> None:
    """NFKC 应把全角字母数字折叠成半角。"""
    assert normalize_text("ＡＢＣ１２３") == "abc123"


def test_normalize_book_name_strips_punctuation_and_spaces() -> None:
    """书名归一化要能穿透《》、空格与标点。"""
    assert normalize_book_name("《三体》") == normalize_book_name("三体")
    assert normalize_book_name("斗破 苍穹") == normalize_book_name("斗破苍穹")


def test_normalize_book_name_handles_roman_numerals() -> None:
    """罗马数字的两种写法应归一化到同一键。"""
    assert normalize_book_name("三体Ⅲ") == normalize_book_name("三体III")


def test_normalize_author_none_is_empty() -> None:
    """作者缺失时返回空串，调用方不必到处判空。"""
    assert normalize_author(None) == ""
    assert normalize_author("  刘慈欣 ") == normalize_author("刘慈欣")


# ---------------------------------------------------------------- 书源


def _make_source(level: CompatibilityLevel) -> BookSource:
    return BookSource(
        id="src_test",
        name="Test",
        url="https://example.com/",
        source_type=SourceType.LEGADO,
        source_format=SourceFormat.LEGADO_JSON,
        compatibility_level=level,
    )


def test_source_url_trailing_slash_stripped() -> None:
    assert _make_source(CompatibilityLevel.L1).url == "https://example.com"


@pytest.mark.parametrize(
    ("level", "required", "expected"),
    [
        (CompatibilityLevel.L2, CompatibilityLevel.L0, True),
        (CompatibilityLevel.L2, CompatibilityLevel.L2, True),
        (CompatibilityLevel.L1, CompatibilityLevel.L2, False),
        (CompatibilityLevel.L0, CompatibilityLevel.L1, False),
    ],
)
def test_source_compatibility_level_is_ordered(
    level: CompatibilityLevel, required: CompatibilityLevel, expected: bool
) -> None:
    """兼容等级是有序的：L2 书源同时满足 L0 / L1。"""
    assert _make_source(level).supports_level(required) is expected


# ---------------------------------------------------------------- 书籍


def test_book_normalized_name_is_autofilled() -> None:
    """未显式提供归一化书名时应自动计算。"""
    book = Book(
        id="bk_1",
        name="《三体》",
        source_id="src_1",
        source_book_url="https://example.com/book/1",
    )
    assert book.normalized_name == normalize_book_name("三体")


# ---------------------------------------------------------------- 章节正文


def test_chapter_content_hash_is_filled_and_stable() -> None:
    """内容哈希应自动填充，且对空白差异不敏感。"""
    first = ChapterContent(
        chapter_id="ch_1", raw_content="a", clean_content="第一章 内容", content_hash=""
    )
    second = ChapterContent(
        chapter_id="ch_1", raw_content="a", clean_content="  第一章   内容  ", content_hash=""
    )
    assert first.content_hash
    assert first.content_hash == second.content_hash


# ---------------------------------------------------------------- 任务状态机


def test_task_transition_happy_path() -> None:
    task = DownloadTask(id="task_1", book_id="bk_1", start_chapter=0, end_chapter=9, total=10)
    assert task.status is TaskStatus.PENDING

    task.transition_to(TaskStatus.RUNNING)
    assert task.started_at is not None

    task.transition_to(TaskStatus.COMPLETED)
    assert task.status is TaskStatus.COMPLETED
    assert task.finished_at is not None


def test_task_illegal_transition_raises() -> None:
    """终态不可再转换 —— 非法转换在领域层就被拒绝。"""
    task = DownloadTask(id="task_2", book_id="bk_1", start_chapter=0, end_chapter=1, total=2)
    task.transition_to(TaskStatus.RUNNING)
    task.transition_to(TaskStatus.CANCELLED)

    with pytest.raises(TaskError):
        task.transition_to(TaskStatus.RUNNING)


def test_task_progress_and_speed() -> None:
    task = DownloadTask(
        id="task_3", book_id="bk_1", start_chapter=0, end_chapter=3, total=4, completed=1, failed=1
    )
    assert task.progress == 0.25
    assert task.processed == 2


def test_can_transition_matrix() -> None:
    assert can_transition(TaskStatus.PAUSED, TaskStatus.RUNNING)
    assert not can_transition(TaskStatus.COMPLETED, TaskStatus.RUNNING)
    # FAILED 允许重试
    assert can_transition(TaskStatus.FAILED, TaskStatus.RUNNING)
