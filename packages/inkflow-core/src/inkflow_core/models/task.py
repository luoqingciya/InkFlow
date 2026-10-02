"""下载任务模型（规划书 §13、§14）。

下载被建模为**任务**而非循环，因此状态机是模型的一部分：
非法状态转换在领域层就被拒绝，而不是等到调度器里出现诡异行为。
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from inkflow_core.errors import TaskError
from inkflow_core.models.enums import TaskItemStatus, TaskStatus
from inkflow_core.utils import utcnow

__all__ = ["TASK_TRANSITIONS", "DownloadTask", "DownloadTaskItem", "can_transition"]

#: 允许的状态转换。终态没有出边（FAILED 除外，允许重试）。
TASK_TRANSITIONS: dict[TaskStatus, frozenset[TaskStatus]] = {
    TaskStatus.PENDING: frozenset({TaskStatus.RUNNING, TaskStatus.CANCELLED, TaskStatus.FAILED}),
    TaskStatus.RUNNING: frozenset(
        {
            TaskStatus.PAUSED,
            TaskStatus.COMPLETED,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
        }
    ),
    TaskStatus.PAUSED: frozenset({TaskStatus.RUNNING, TaskStatus.CANCELLED, TaskStatus.FAILED}),
    TaskStatus.COMPLETED: frozenset(),
    TaskStatus.FAILED: frozenset({TaskStatus.RUNNING}),
    TaskStatus.CANCELLED: frozenset(),
}


def can_transition(src: TaskStatus, dst: TaskStatus) -> bool:
    """判断状态转换是否合法。"""
    return dst in TASK_TRANSITIONS.get(src, frozenset())


class DownloadTask(BaseModel):
    """一次下载任务。"""

    model_config = ConfigDict(extra="ignore")

    id: str

    book_id: str

    status: TaskStatus = TaskStatus.PENDING

    # 章节区间为闭区间，索引从 0 开始，与 Chapter.index 一致
    start_chapter: int = Field(ge=0)
    end_chapter: int = Field(ge=0)

    total: int = Field(default=0, ge=0)
    completed: int = Field(default=0, ge=0)
    failed: int = Field(default=0, ge=0)

    concurrency: int = Field(default=4, ge=1, le=64)

    output_format: str = "epub"
    output_path: str = ""

    # 失败原因摘要，仅在 FAILED 时有意义
    error: str | None = None

    created_at: datetime = Field(default_factory=utcnow)
    started_at: datetime | None = None
    finished_at: datetime | None = None

    @property
    def progress(self) -> float:
        """完成进度，取值 0.0 ~ 1.0。"""
        if self.total <= 0:
            return 0.0
        return min(1.0, self.completed / self.total)

    @property
    def processed(self) -> int:
        """已处理（成功 + 失败）的章节数。"""
        return self.completed + self.failed

    @property
    def elapsed_seconds(self) -> float:
        """已运行秒数。未开始为 0，已结束为总耗时。"""
        if self.started_at is None:
            return 0.0
        end = self.finished_at or utcnow()
        return max(0.0, (end - self.started_at).total_seconds())

    @property
    def chapters_per_second(self) -> float:
        """平均下载速度（章/秒）。"""
        elapsed = self.elapsed_seconds
        if elapsed <= 0:
            return 0.0
        return self.completed / elapsed

    def transition_to(self, target: TaskStatus) -> None:
        """执行状态转换。

        Raises:
            TaskError: 转换不合法。
        """
        if not can_transition(self.status, target):
            raise TaskError(
                f"任务 {self.id} 无法从 {self.status} 转换为 {target}",
                details={"task_id": self.id, "from": str(self.status), "to": str(target)},
            )
        self.status = target
        now = utcnow()
        if target is TaskStatus.RUNNING and self.started_at is None:
            self.started_at = now
        if target.is_terminal:
            self.finished_at = now


class DownloadTaskItem(BaseModel):
    """任务中的单个章节（对应 ``download_task_items`` 表）。

    单章级别的重试计数与错误信息记在这里，任务级只保留汇总数字。
    """

    model_config = ConfigDict(extra="ignore")

    id: str
    task_id: str

    chapter_id: str
    chapter_index: int = Field(ge=0)
    chapter_name: str

    status: TaskItemStatus = TaskItemStatus.PENDING
    attempts: int = Field(default=0, ge=0)
    error: str | None = None

    started_at: datetime | None = None
    finished_at: datetime | None = None
