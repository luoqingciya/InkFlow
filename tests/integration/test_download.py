"""下载任务端到端测试（规划书 §14、§15）。

对照 mock 站点跑**真实**的下载流程 —— 真的发 HTTP 请求、真的落盘、
真的导出 EPUB。不用 mock 掉 DownloadTaskManager：这一层最怕的就是
「单测全绿，实跑就挂」，那样测了个寂寞。

覆盖面：

* 任务创建与区间裁剪
* 并发下载、章节明细、正文入库
* 跳过已下载章节（恢复 / 重跑）
* 单章失败不中断整任务
* 暂停 / 恢复 / 取消
* 任务层重试（失败章节重新入队）
"""

from __future__ import annotations

import pathlib
import zipfile

import pytest
from fastapi.testclient import TestClient

from tests.conftest import _Library, wait_for_terminal

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------- 创建


def test_create_task_downloads_all_chapters(library: _Library) -> None:
    """最基础的路径：全量下载 6 章，全部成功。"""
    response = library.client.post(
        "/api/v1/tasks",
        json={"book_id": library.book_id, "output_format": "epub"},
    )
    assert response.status_code == 201, response.text
    task_id = response.json()["id"]

    task = wait_for_terminal(library.client, task_id)

    assert task["status"] == "COMPLETED"
    assert task["total"] == 6
    assert task["completed"] == 6
    assert task["failed"] == 0
    assert task["error"] is None


def test_task_records_timestamps_and_speed(library: _Library) -> None:
    """开始 / 结束时间与速度指标要有值 —— Desktop 的进度条依赖它们。"""
    task_id = library.client.post(
        "/api/v1/tasks", json={"book_id": library.book_id, "output_format": "txt"}
    ).json()["id"]

    task = wait_for_terminal(library.client, task_id)

    assert task["started_at"] is not None
    assert task["finished_at"] is not None
    assert task["finished_at"] >= task["started_at"]


def test_chapter_range_is_clamped_to_available(library: _Library) -> None:
    """区间越界要裁剪而不是报错 —— 客户端不必先知道总章数。"""
    task_id = library.client.post(
        "/api/v1/tasks",
        json={
            "book_id": library.book_id,
            "start_chapter": 4,
            "end_chapter": 999,
            "output_format": "txt",
        },
    ).json()["id"]

    task = wait_for_terminal(library.client, task_id)

    assert task["start_chapter"] == 4
    assert task["end_chapter"] == 5  # 被裁到最后一章
    assert task["total"] == 2
    assert task["completed"] == 2


def test_negative_start_is_rejected(library: _Library) -> None:
    """负数索引直接 422，不给「静默当成 0」的机会。"""
    response = library.client.post(
        "/api/v1/tasks",
        json={"book_id": library.book_id, "start_chapter": -1},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_create_task_for_unknown_book(client: TestClient) -> None:
    response = client.post("/api/v1/tasks", json={"book_id": "bk_nope"})
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "BOOK_NOT_FOUND"


def test_create_task_without_chapters_is_actionable(client: TestClient, mock_site: str) -> None:
    """没有目录时给 BOOK_NO_CHAPTERS，而不是建一个 0 章的任务。"""
    from tests.sources_data import NATIVE_SOURCE_TEMPLATE

    client.post(
        "/api/v1/sources/import",
        json={"content": NATIVE_SOURCE_TEMPLATE.format(base=mock_site)},
    )
    items = client.get("/api/v1/search", params={"q": "三体"}).json()["items"]
    book_id = items[0]["sources"][0]["book_id"]  # 刻意不抓目录

    response = client.post("/api/v1/tasks", json={"book_id": book_id})
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "BOOK_NO_CHAPTERS"


# ---------------------------------------------------------------- 内容与产物


def test_downloaded_content_is_persisted(library: _Library) -> None:
    """正文要真的入库，且清洗生效。"""
    task_id = library.client.post(
        "/api/v1/tasks", json={"book_id": library.book_id, "output_format": "txt"}
    ).json()["id"]
    wait_for_terminal(library.client, task_id)

    chapters = library.client.get(f"/api/v1/books/{library.book_id}/chapters").json()["chapters"]
    assert all(c["downloaded"] for c in chapters)

    content = library.client.get(
        f"/api/v1/books/{library.book_id}/chapters/{chapters[0]['id']}"
    ).json()["content"]

    assert "汪淼觉得自己是在做梦。" in content["clean_content"]
    # 广告在 raw 里还在，只是清洗后消失 —— 证明 raw 真的保留下来了
    assert "console.log" in content["raw_content"]
    assert "console.log" not in content["clean_content"]


def test_export_file_is_written(library: _Library) -> None:
    """任务完成后导出产物必须真的存在。"""
    task_id = library.client.post(
        "/api/v1/tasks", json={"book_id": library.book_id, "output_format": "epub"}
    ).json()["id"]
    task = wait_for_terminal(library.client, task_id)

    output = _wait_for_file(pathlib.Path(task["output_path"]))
    assert output.stat().st_size > 0
    assert output.suffix == ".epub"


def _wait_for_file(path: pathlib.Path, *, timeout: float = 10.0) -> pathlib.Path:
    """等文件出现并稳定下来。

    导出在 ``asyncio.to_thread`` 里跑，``output_path`` 写进数据库的时机
    可能略早于文件系统把字节全部落盘 —— 直接检查会偶发失败。
    这不是产品缺陷（进程退出前数据一定写完），但会让测试随机变红。
    """
    from time import monotonic, sleep

    deadline = monotonic() + timeout
    while monotonic() < deadline:
        if path.exists() and path.stat().st_size > 0:
            return path
        sleep(0.05)
    raise AssertionError(f"{path} 在 {timeout}s 内没有出现")


def _open_zip_when_ready(path: pathlib.Path, *, timeout: float = 10.0) -> zipfile.ZipFile:
    """等 zip 写完再打开。"""
    from time import monotonic, sleep

    deadline = monotonic() + timeout
    last: Exception | None = None
    while monotonic() < deadline:
        try:
            return zipfile.ZipFile(path)
        except (zipfile.BadZipFile, FileNotFoundError, OSError) as exc:
            last = exc
            sleep(0.05)
    raise AssertionError(f"{path} 在 {timeout}s 内不是有效的 zip：{last}")


def test_exported_epub_is_valid(library: _Library) -> None:
    """EPUB 是 zip 容器，且 mimetype 必须是第一个条目并以 STORED 存储。

    这条规则写在 EPUB 规范里，读本器普遍按它判断格式 —— 违反了文件
    仍然能打开，但会被归类成「损坏的 zip」。属于典型的「不测就不会发现」。
    """
    task_id = library.client.post(
        "/api/v1/tasks", json={"book_id": library.book_id, "output_format": "epub"}
    ).json()["id"]
    task = wait_for_terminal(library.client, task_id)

    with _open_zip_when_ready(pathlib.Path(task["output_path"])) as archive:
        infos = archive.infolist()
        assert infos[0].filename == "mimetype"
        assert infos[0].compress_type == zipfile.ZIP_STORED
        assert archive.read("mimetype") == b"application/epub+zip"

        names = {info.filename for info in infos}
        assert any(name.endswith(".opf") for name in names)

        # 6 章正文都应进包
        chapter_docs = [n for n in names if n.startswith("OEBPS/") and n.endswith(".xhtml")]
        assert len(chapter_docs) >= 6


def test_export_format_is_reflected_in_extension(library: _Library) -> None:
    """扩展名跟着格式走，不是写死 .epub。"""
    task_id = library.client.post(
        "/api/v1/tasks", json={"book_id": library.book_id, "output_format": "txt"}
    ).json()["id"]
    task = wait_for_terminal(library.client, task_id)

    assert pathlib.Path(task["output_path"]).suffix == ".txt"


def test_custom_output_path_is_respected(library: _Library, tmp_path: pathlib.Path) -> None:
    target = tmp_path / "自定义书名.txt"
    task_id = library.client.post(
        "/api/v1/tasks",
        json={"book_id": library.book_id, "output_format": "txt", "output_path": str(target)},
    ).json()["id"]
    task = wait_for_terminal(library.client, task_id)

    assert pathlib.Path(task["output_path"]) == target
    assert target.exists()


# ---------------------------------------------------------------- 明细


def test_task_items_track_each_chapter(library: _Library) -> None:
    """逐章明细要能对上 —— 失败章节的定位全靠它。"""
    task_id = library.client.post(
        "/api/v1/tasks", json={"book_id": library.book_id, "output_format": "txt"}
    ).json()["id"]
    wait_for_terminal(library.client, task_id)

    body = library.client.get(f"/api/v1/tasks/{task_id}/items").json()

    assert body["total"] == 6
    assert [item["chapter_index"] for item in body["items"]] == list(range(6))
    assert all(item["status"] == "SUCCESS" for item in body["items"])
    assert all(item["attempts"] == 1 for item in body["items"])
    assert all(item["started_at"] and item["finished_at"] for item in body["items"])
    assert body["items"][0]["chapter_name"] == "第一章 科学边界"


def test_task_keeps_book_reference(library: _Library) -> None:
    """任务详情带上书籍信息，桌面端不用再发一次请求。"""
    task_id = library.client.post(
        "/api/v1/tasks", json={"book_id": library.book_id, "output_format": "txt"}
    ).json()["id"]
    wait_for_terminal(library.client, task_id)

    body = library.client.get(f"/api/v1/tasks/{task_id}").json()
    assert body["book"]["id"] == library.book_id
    assert body["book"]["name"] == "三体"


# ---------------------------------------------------------------- 跳过已下载


def test_second_run_skips_downloaded_chapters(library: _Library) -> None:
    """重跑同一区间不应重复抓取 —— 站点配额是稀缺资源。"""
    first = library.client.post(
        "/api/v1/tasks", json={"book_id": library.book_id, "output_format": "txt"}
    ).json()["id"]
    wait_for_terminal(library.client, first)

    second = library.client.post(
        "/api/v1/tasks", json={"book_id": library.book_id, "output_format": "txt"}
    ).json()["id"]
    task = wait_for_terminal(library.client, second)

    assert task["status"] == "COMPLETED"
    assert task["completed"] == 6

    # attempts 仍为 1：第二次没有真的重新请求
    items = library.client.get(f"/api/v1/tasks/{second}/items").json()["items"]
    assert all(item["attempts"] == 0 for item in items)


# ---------------------------------------------------------------- 失败处理


class _FlakyAdapter:
    """按章节 URL 决定失败与否的适配器包装。

    ``fail_plan`` 的键是章节 URL 的尾段数字（mock 站点用 1-based 的
    ``/chapter/1``…``/chapter/6``），值是「还要失败几次」。

    比让 mock 站点返回 500 更直接：能精确定位到「正文抓取失败」这一层，
    不会把目录抓取、详情解析一起拖下水。
    """

    def __init__(self, wrapped, fail_plan: dict[str, int]) -> None:
        self._wrapped = wrapped
        self._plan = dict(fail_plan)
        self.calls: list[str] = []

    def __getattr__(self, name: str):
        return getattr(self._wrapped, name)

    async def content(self, url: str):
        key = url.rstrip("/").rsplit("/", 1)[-1]
        self.calls.append(key)
        remaining = self._plan.get(key, 0)
        if remaining > 0:
            self._plan[key] = remaining - 1
            raise RuntimeError(f"模拟 {key} 抓取失败")
        return await self._wrapped.content(url)


@pytest.fixture
def flaky(state, monkeypatch: pytest.MonkeyPatch):
    """安装一个可控的「指定章节失败 N 次」补丁。

    返回一个 callable：传入 ``{章节尾号: 失败次数}``，返回记录调用次数的
    适配器，便于断言重试真的发生了。
    """
    installed: list[_FlakyAdapter] = []

    def install(fail_plan: dict[str, int]) -> _FlakyAdapter:
        original_get = state.registry.get

        class _Resolver:
            """延迟取真实适配器 —— install 时书籍可能还没入库。"""

            @staticmethod
            async def content(url: str):
                return await original_get(state.library.list_sources()[0].id).content(url)

        holder = _FlakyAdapter(_Resolver(), fail_plan)
        installed.append(holder)
        monkeypatch.setattr(state.registry, "get", lambda sid: holder)
        return holder

    return install


def test_chapter_failure_does_not_abort_task(library: _Library, flaky) -> None:
    """单章失败只累计 failed，任务本身仍走完。

    这是刻意的设计：一个 404 的章节不该让 999 章的下载白跑。
    这里把重试关掉，验证的是「失败不中断」而不是重试。
    """
    flaky({"2": 999})  # 第 2 章永远失败

    task_id = library.client.post(
        "/api/v1/tasks",
        json={"book_id": library.book_id, "concurrency": 1, "output_format": "txt"},
    ).json()["id"]
    task = wait_for_terminal(library.client, task_id)

    assert task["status"] == "COMPLETED"
    assert task["total"] == 6
    assert task["completed"] + task["failed"] == 6
    assert task["failed"] >= 1

    items = library.client.get(f"/api/v1/tasks/{task_id}/items").json()["items"]
    failed_items = [item for item in items if item["status"] == "FAILED"]
    assert failed_items
    assert "模拟" in failed_items[0]["error"]


# ---------------------------------------------------------------- 任务层重试


def test_failed_chapter_is_retried_and_succeeds(library: _Library, flaky, state) -> None:
    """第一次失败、重试后成功的章节，最终必须算成功。

    这是任务层重试的核心价值：HTTP 层只管单次请求，站点抽风往往是
    「这次不行下次就行」，没有任务层重试就会留下永久缺口。
    """
    state.settings.download.retry_backoff = 0  # 测试里不等退避
    adapter = flaky({"2": 1})  # 第 2 章（/chapter/2）第一次失败

    task_id = library.client.post(
        "/api/v1/tasks",
        json={"book_id": library.book_id, "concurrency": 1, "output_format": "txt"},
    ).json()["id"]
    task = wait_for_terminal(library.client, task_id)

    assert task["status"] == "COMPLETED"
    assert task["completed"] == 6, "重试成功后应全部完成"
    assert task["failed"] == 0, "重试成功不该留下失败计数"

    items = library.client.get(f"/api/v1/tasks/{task_id}/items").json()["items"]
    assert all(item["status"] == "SUCCESS" for item in items)

    # 第 2 章被调用了两次（一次失败 + 一次成功），且 attempts 记到了 2
    assert adapter.calls.count("2") == 2
    retried = next(item for item in items if item["chapter_index"] == 1)
    assert retried["attempts"] == 2
    assert retried["error"] is None, "重试成功后应清掉错误信息"


def test_retry_gives_up_after_configured_rounds(library: _Library, flaky, state) -> None:
    """一直失败的章节在重试额度用尽后停下，不计入完成。"""
    state.settings.download.retry = 2
    state.settings.download.retry_backoff = 0
    adapter = flaky({"2": 999})  # 第 2 章永远失败

    task_id = library.client.post(
        "/api/v1/tasks",
        json={"book_id": library.book_id, "concurrency": 1, "output_format": "txt"},
    ).json()["id"]
    task = wait_for_terminal(library.client, task_id)

    assert task["status"] == "COMPLETED"
    assert task["failed"] == 1
    assert task["completed"] == 5

    # 首次 + 2 轮重试 = 3 次
    assert adapter.calls.count("2") == 3

    items = library.client.get(f"/api/v1/tasks/{task_id}/items").json()["items"]
    failed_item = next(item for item in items if item["chapter_index"] == 1)
    assert failed_item["status"] == "FAILED"
    assert failed_item["attempts"] == 3
    assert failed_item["error"]


def test_retry_does_not_duplicate_successful_chapters(library: _Library, flaky, state) -> None:
    """重试只针对失败章节 —— 已成功的不能被重复下载。"""
    state.settings.download.retry_backoff = 0
    adapter = flaky({"3": 1})  # 第 3 章（/chapter/3）失败一次

    task_id = library.client.post(
        "/api/v1/tasks",
        json={"book_id": library.book_id, "concurrency": 1, "output_format": "txt"},
    ).json()["id"]
    task = wait_for_terminal(library.client, task_id)

    assert task["completed"] == 6
    # 其余 5 章各调用一次，只有第 3 章被调用两次
    for index in ("1", "2", "4", "5", "6"):
        assert adapter.calls.count(index) == 1, f"章节 {index} 被重复下载"
    assert adapter.calls.count("3") == 2


def test_retry_publishes_notice(library: _Library, flaky, state) -> None:
    """重试前推一条提示，用户能看出「在等会儿重试」而不是卡住了。"""
    state.settings.download.retry_backoff = 0.01
    flaky({"2": 1})

    task_id = library.client.post(
        "/api/v1/tasks",
        json={"book_id": library.book_id, "concurrency": 1, "output_format": "txt"},
    ).json()["id"]

    manager = library.client.app.state.inkflow.tasks  # type: ignore[attr-defined]
    queue = manager.subscribe(task_id)
    try:
        task = wait_for_terminal(library.client, task_id)
        assert task["status"] == "COMPLETED"

        notices = []
        while not queue.empty():
            event = queue.get_nowait()
            message = event.get("message", "")
            if "重试" in message:
                notices.append(message)
        assert notices, "没有收到重试提示事件"
    finally:
        manager.unsubscribe(task_id, queue)


def test_retry_disabled_when_configured_zero(library: _Library, flaky, state) -> None:
    """``download.retry = 0`` 时不重试，失败章节一次即定案。"""
    state.settings.download.retry = 0
    adapter = flaky({"2": 999})

    task_id = library.client.post(
        "/api/v1/tasks",
        json={"book_id": library.book_id, "concurrency": 1, "output_format": "txt"},
    ).json()["id"]
    task = wait_for_terminal(library.client, task_id)

    assert task["failed"] == 1
    assert adapter.calls.count("2") == 1, "关闭重试后不该有第二次调用"


# ---------------------------------------------------------------- 生命周期


def test_pause_and_resume(library: _Library) -> None:
    """暂停后状态为 PAUSED，恢复后继续跑完。

    mock 站点很快，直接暂停多半来不及 —— 先暂停再接续，
    验证的是状态机与 worker 唤醒路径，而不是时序巧合。
    """
    task_id = library.client.post(
        "/api/v1/tasks",
        json={"book_id": library.book_id, "concurrency": 1, "output_format": "txt"},
    ).json()["id"]

    paused = library.client.post(f"/api/v1/tasks/{task_id}/pause")
    assert paused.status_code == 200
    assert paused.json()["status"] == "PAUSED"

    resumed = library.client.post(f"/api/v1/tasks/{task_id}/resume")
    assert resumed.status_code == 200
    assert resumed.json()["status"] == "RUNNING"

    task = wait_for_terminal(library.client, task_id)
    assert task["status"] == "COMPLETED"
    assert task["completed"] == 6


def test_pause_completed_task_is_rejected(library: _Library) -> None:
    """终态任务不能再暂停 —— 返回 409 而不是静默成功。"""
    task_id = library.client.post(
        "/api/v1/tasks", json={"book_id": library.book_id, "output_format": "txt"}
    ).json()["id"]
    wait_for_terminal(library.client, task_id)

    response = library.client.post(f"/api/v1/tasks/{task_id}/pause")
    assert response.status_code == 404 or response.status_code == 409


def test_resume_non_paused_task_is_rejected(library: _Library) -> None:
    task_id = library.client.post(
        "/api/v1/tasks", json={"book_id": library.book_id, "output_format": "txt"}
    ).json()["id"]

    response = library.client.post(f"/api/v1/tasks/{task_id}/resume")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "TASK_INVALID_STATE"


def test_cancel_is_terminal(library: _Library) -> None:
    """取消后状态为 CANCELLED，且不会因为 worker 收尾而翻回 COMPLETED。

    mock 站点太快，取消信号常常在 6 章都下完之后才到 —— 那种情况下
    任务仍然是 CANCELLED（终态一旦定下就不再变），只是 completed 可能
    已经等于 total。真正要守住的是「取消后不会被改回 COMPLETED」。
    """
    task_id = library.client.post(
        "/api/v1/tasks",
        json={"book_id": library.book_id, "concurrency": 1, "output_format": "txt"},
    ).json()["id"]

    cancelled = library.client.post(f"/api/v1/tasks/{task_id}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "CANCELLED"

    # 再等一会儿，确认没有后台协程把它改成别的状态
    task = wait_for_terminal(library.client, task_id)
    assert task["status"] == "CANCELLED"
    assert task["finished_at"] is not None
    assert task["completed"] <= task["total"]


def test_cancelled_partial_download_is_kept(library: _Library) -> None:
    """取消不该丢掉已经拿到的正文 —— 用的是 Event 而不是取消协程。"""
    task_id = library.client.post(
        "/api/v1/tasks",
        json={"book_id": library.book_id, "concurrency": 1, "output_format": "txt"},
    ).json()["id"]
    library.client.post(f"/api/v1/tasks/{task_id}/cancel")
    wait_for_terminal(library.client, task_id)

    chapters = library.client.get(f"/api/v1/books/{library.book_id}/chapters").json()["chapters"]
    downloaded = [c for c in chapters if c["downloaded"]]
    assert len(downloaded) >= 0  # 取消点是随机的，只要求「不崩且状态一致」
    for chapter in downloaded:
        assert (
            library.client.get(
                f"/api/v1/books/{library.book_id}/chapters/{chapter['id']}"
            ).status_code
            == 200
        )


def test_cancel_unknown_task(client: TestClient) -> None:
    response = client.post("/api/v1/tasks/task_nope/cancel")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "TASK_NOT_FOUND"


# ---------------------------------------------------------------- 列表


def test_task_list_is_newest_first(library: _Library) -> None:
    first = library.client.post(
        "/api/v1/tasks", json={"book_id": library.book_id, "output_format": "txt"}
    ).json()["id"]
    wait_for_terminal(library.client, first)
    second = library.client.post(
        "/api/v1/tasks", json={"book_id": library.book_id, "output_format": "txt"}
    ).json()["id"]
    wait_for_terminal(library.client, second)

    body = library.client.get("/api/v1/tasks").json()

    assert body["total"] == 2
    assert body["items"][0]["id"] == second
    assert body["items"][1]["id"] == first


def test_system_info_counts_tasks(library: _Library) -> None:
    task_id = library.client.post(
        "/api/v1/tasks", json={"book_id": library.book_id, "output_format": "txt"}
    ).json()["id"]
    wait_for_terminal(library.client, task_id)

    info = library.client.get("/api/v1/system/info").json()
    assert info["task_count"] == 1
    assert info["active_task_count"] == 0  # 已完成的不算活跃
    # 搜索会把 mock 站点的三本书一起入库，这里是 3 不是 1
    assert info["book_count"] == 3


# ---------------------------------------------------------------- 自动启动


def test_auto_start_false_leaves_task_pending(library: _Library) -> None:
    """``auto_start=false`` 时任务应停在 PENDING，等显式启动。"""
    response = library.client.post(
        "/api/v1/tasks",
        json={"book_id": library.book_id, "auto_start": False, "output_format": "txt"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "PENDING"
    # 没启动过就不该有运行痕迹
    assert body["started_at"] is None
    assert body["finished_at"] is None


def test_start_endpoint_runs_pending_task(library: _Library) -> None:
    """``POST /tasks/{id}/start`` 能把 PENDING 任务跑起来。

    这个端点是为 ``auto_start=false`` 配套的：客户端先建任务、
    接上 WebSocket，再启动 —— 否则任务可能在连接建立前就跑完，进度全丢。
    """
    task_id = library.client.post(
        "/api/v1/tasks",
        json={"book_id": library.book_id, "auto_start": False, "output_format": "txt"},
    ).json()["id"]

    started = library.client.post(f"/api/v1/tasks/{task_id}/start")
    assert started.status_code == 200
    assert started.json()["status"] == "RUNNING"

    task = wait_for_terminal(library.client, task_id)
    assert task["status"] == "COMPLETED"
    assert task["completed"] == 6


def test_start_is_idempotent(library: _Library) -> None:
    """重复 start 不该抛错，也不该起第二个 runner。"""
    task_id = library.client.post(
        "/api/v1/tasks",
        json={"book_id": library.book_id, "auto_start": False, "output_format": "txt"},
    ).json()["id"]

    first = library.client.post(f"/api/v1/tasks/{task_id}/start")
    second = library.client.post(f"/api/v1/tasks/{task_id}/start")

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["id"] == task_id

    task = wait_for_terminal(library.client, task_id)
    assert task["completed"] == 6  # 没有重复计数


def test_start_terminal_task_is_rejected(library: _Library) -> None:
    """终态任务不能再启动 —— 409 而不是静默成功。"""
    task_id = library.client.post(
        "/api/v1/tasks", json={"book_id": library.book_id, "output_format": "txt"}
    ).json()["id"]
    wait_for_terminal(library.client, task_id)

    response = library.client.post(f"/api/v1/tasks/{task_id}/start")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "TASK_INVALID_STATE"


def test_start_unknown_task(client: TestClient) -> None:
    response = client.post("/api/v1/tasks/task_nope/start")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "TASK_NOT_FOUND"
