"""日志配置测试（规划书 §28）。

日志最容易「看起来配好了其实没生效」：``basicConfig`` 被 uvicorn 抢先、
handler 挂错 logger、编码不对导致中文乱码。所以这里不满足于
「函数被调用了」，而是**真的写一条日志，再把它从文件里读回来**。
"""

from __future__ import annotations

import json
import logging
import logging.handlers
from collections.abc import Iterator
from pathlib import Path

import pytest

from inkflow_core import log as log_module
from inkflow_core.config import LogConfig
from inkflow_core.log import LOG_FILENAME, setup_logging

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _isolate_root_logger() -> Iterator[None]:
    """还原 root logger 与模块状态。

    日志是**进程级**状态，不还原会互相污染：前一个用例加的 handler
    会把后一个用例的日志也写进前一个的临时目录。
    """
    root = logging.getLogger()
    saved_handlers = root.handlers[:]
    saved_level = root.level
    log_module._file_handler = None

    yield

    for handler in root.handlers[:]:
        if handler not in saved_handlers:
            root.removeHandler(handler)
            handler.close()
    root.handlers[:] = saved_handlers
    root.setLevel(saved_level)
    log_module._file_handler = None


def _read_log(tmp_path: Path) -> str:
    return (tmp_path / LOG_FILENAME).read_text(encoding="utf-8")


def _file_handlers() -> list[logging.Handler]:
    root = logging.getLogger()
    return [h for h in root.handlers if isinstance(h, logging.handlers.RotatingFileHandler)]


# ================================================================ 真的落盘


def test_log_line_reaches_file(tmp_path: Path) -> None:
    """核心断言：写一条日志，它得出现在文件里。"""
    setup_logging(LogConfig(), tmp_path)

    logging.getLogger("inkflow.test").warning("落盘测试")

    assert "落盘测试" in _read_log(tmp_path)


def test_file_is_not_created_before_first_write(tmp_path: Path) -> None:
    """handler 用 delay=True —— 没日志就不该留下空文件。"""
    setup_logging(LogConfig(), tmp_path)

    assert not (tmp_path / LOG_FILENAME).exists()


def test_chinese_survives_roundtrip(tmp_path: Path) -> None:
    """必须显式用 utf-8：Windows 默认 cp1252 会让中文乱码甚至抛异常。"""
    setup_logging(LogConfig(), tmp_path)

    logging.getLogger("inkflow.test").warning("三体 —— 第一章 科学边界")

    assert "三体 —— 第一章 科学边界" in _read_log(tmp_path)


def test_logger_name_and_level_are_recorded(tmp_path: Path) -> None:
    setup_logging(LogConfig(), tmp_path)

    logging.getLogger("inkflow.api").error("出错了")

    content = _read_log(tmp_path)
    assert "inkflow.api" in content
    assert "ERROR" in content


# ================================================================ 级别


def test_level_filters_lower_records(tmp_path: Path) -> None:
    setup_logging(LogConfig(level="WARNING"), tmp_path)
    logger = logging.getLogger("inkflow.test")

    logger.info("这条不该出现")
    logger.warning("这条该出现")

    content = _read_log(tmp_path)
    assert "这条不该出现" not in content
    assert "这条该出现" in content


def test_level_is_uppercased_by_config(tmp_path: Path) -> None:
    """配置里的级别大小写不敏感。"""
    config = LogConfig(level="debug")

    assert config.level == "DEBUG"


def test_debug_records_land_when_level_is_debug(tmp_path: Path) -> None:
    setup_logging(LogConfig(level="DEBUG"), tmp_path)

    logging.getLogger("inkflow.test").debug("调试信息")

    assert "调试信息" in _read_log(tmp_path)


# ================================================================ 幂等


def test_setup_is_idempotent(tmp_path: Path) -> None:
    """重复调用不该叠加 handler —— 否则每条日志会被写多遍。"""
    first = setup_logging(LogConfig(), tmp_path)
    handler_count = len(logging.getLogger().handlers)

    second = setup_logging(LogConfig(), tmp_path)

    assert second is first
    assert len(logging.getLogger().handlers) == handler_count


def test_repeated_setup_does_not_duplicate_lines(tmp_path: Path) -> None:
    """幂等的真正意义：日志文件里只有一行，不是两行。"""
    setup_logging(LogConfig(), tmp_path)
    setup_logging(LogConfig(), tmp_path)

    logging.getLogger("inkflow.test").warning("只应出现一次")

    assert _read_log(tmp_path).count("只应出现一次") == 1


# ================================================================ 轮转


def test_rotation_follows_config(tmp_path: Path) -> None:
    setup_logging(LogConfig(rotate_max_mb=7, rotate_backups=3), tmp_path)

    handlers = _file_handlers()
    assert len(handlers) == 1
    assert handlers[0].maxBytes == 7 * 1024 * 1024  # type: ignore[attr-defined]
    assert handlers[0].backupCount == 3  # type: ignore[attr-defined]


def test_rotates_when_exceeding_max_size(tmp_path: Path) -> None:
    """真的写超上限，看轮转文件有没有出现 —— 不只是读配置。"""
    setup_logging(LogConfig(rotate_max_mb=1, rotate_backups=2), tmp_path)
    logger = logging.getLogger("inkflow.test")

    # 每条约 1KB，写 1200 条 ≈ 1.2MB，必然越过 1MB 上限
    for index in range(1200):
        logger.info("填充 %04d %s", index, "x" * 1000)

    assert (tmp_path / LOG_FILENAME).exists()
    assert (tmp_path / f"{LOG_FILENAME}.1").exists()


# ================================================================ JSON Lines


def test_json_is_one_object_per_line(tmp_path: Path) -> None:
    """JSON Lines 的意义就在「一行一条」—— 采集器才能逐行解析。"""
    setup_logging(LogConfig(json_logs=True), tmp_path)
    logger = logging.getLogger("inkflow.test")

    logger.info("第一条")
    logger.info("第二条")

    lines = [line for line in _read_log(tmp_path).splitlines() if line.strip()]
    assert len(lines) == 2
    for line in lines:
        json.loads(line)


def test_json_has_standard_fields(tmp_path: Path) -> None:
    setup_logging(LogConfig(json_logs=True), tmp_path)

    logging.getLogger("inkflow.api").warning("结构化")

    payload = json.loads(_read_log(tmp_path).strip())
    assert payload["level"] == "WARNING"
    assert payload["logger"] == "inkflow.api"
    assert payload["message"] == "结构化"
    assert payload["ts"]


def test_json_includes_extra_fields(tmp_path: Path) -> None:
    """``extra=`` 传进来的业务字段要能被检索到。"""
    setup_logging(LogConfig(json_logs=True), tmp_path)

    logging.getLogger("inkflow.test").info("带上下文", extra={"task_id": "task_123"})

    payload = json.loads(_read_log(tmp_path).strip())
    assert payload["task_id"] == "task_123"


def test_json_includes_exception(tmp_path: Path) -> None:
    setup_logging(LogConfig(json_logs=True), tmp_path)

    try:
        raise ValueError("炸了")
    except ValueError:
        logging.getLogger("inkflow.test").exception("出错了")

    payload = json.loads(_read_log(tmp_path).strip())
    assert "ValueError" in payload["exception"]
    assert "炸了" in payload["exception"]


def test_json_omits_internal_record_fields(tmp_path: Path) -> None:
    """标准 LogRecord 属性不该混进输出，否则每条日志都拖一堆噪音。"""
    setup_logging(LogConfig(json_logs=True), tmp_path)

    logging.getLogger("inkflow.test").info("干净")

    payload = json.loads(_read_log(tmp_path).strip())
    assert "args" not in payload
    assert "pathname" not in payload
    assert "relativeCreated" not in payload


def test_text_format_used_when_json_disabled(tmp_path: Path) -> None:
    setup_logging(LogConfig(json_logs=False), tmp_path)

    logging.getLogger("inkflow.test").warning("纯文本")

    line = _read_log(tmp_path).strip()
    assert not line.startswith("{")
    assert "纯文本" in line


# ================================================================ 降级


def test_unwritable_logs_dir_returns_none(tmp_path: Path) -> None:
    """日志目录建不出来时返回 None，而不是抛错带走整个服务。"""
    blocker = tmp_path / "logs"
    blocker.write_text("占位成文件，mkdir 会失败", encoding="utf-8")

    handler = setup_logging(LogConfig(), blocker)

    assert handler is None


def test_console_still_works_when_file_unavailable(tmp_path: Path) -> None:
    """文件写不了也要有控制台输出 —— 不能变成「完全没有日志」。"""
    blocker = tmp_path / "logs"
    blocker.write_text("占位", encoding="utf-8")

    setup_logging(LogConfig(), blocker)

    assert logging.getLogger().handlers
