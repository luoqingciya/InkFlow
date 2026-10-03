"""量一量 JS sidecar 的冷启动到底吃掉多少。

**为什么要这个**：Windows CI 上 `test_evaluates_expression` 偶发
「JS 执行超时（10s 无响应）」。那 10s 是 Python 侧的兜底
（测试里 `timeout=5.0`，兜底 = `5.0 + 5.0`），它**从写完请求开始算** ——
也就是说**进程启动的时间也算在规则执行的预算里**。

这个脚本用来量那段到底多长，以及加上负载之后会变成多少。

用法：

    uv run python scripts/measure_js_startup.py --rounds 10
    uv run python scripts/measure_js_startup.py --rounds 10 --load 4

`--load N` 会起 N 个占满 CPU 的进程，模拟「runner 上有别的重活在跑」——
CI 上那次抖动正是紧跟在最重的下载 / 起服务类测试之后。
"""

from __future__ import annotations

import argparse
import asyncio
import multiprocessing
import statistics
import time
from typing import Any

from inkflow_core.config import JsConfig
from inkflow_js_runtime import JsRuntime, JsRuntimeError, find_node

#: 量的时候把超时放宽 —— 要的是**数字**，不是看它超时。
MEASURE_TIMEOUT = 60.0


def _burn(stop: Any) -> None:
    """占满一个核，直到收到停止信号。

    参数标注成 ``Any``：``multiprocessing.Event`` 是个工厂函数，不是类型，
    而它的真实类型在私有模块 ``multiprocessing.synchronize`` 里。
    """
    while not stop.is_set():
        sum(i * i for i in range(10_000))


async def one_round() -> float:
    """冷启动一次，返回「spawn 到第一次求值返回」的秒数。"""
    runtime = JsRuntime(JsConfig(enabled=True, timeout=MEASURE_TIMEOUT))
    try:
        started = time.perf_counter()
        await runtime.eval("1 + 1")
        return time.perf_counter() - started
    finally:
        await runtime.close()


async def measure(rounds: int) -> list[float]:
    samples: list[float] = []
    for index in range(rounds):
        try:
            seconds = await one_round()
        except JsRuntimeError as exc:
            print(f"  第 {index + 1} 轮失败：{exc}")
            continue
        samples.append(seconds)
        print(f"  第 {index + 1} 轮：{seconds:.3f}s")
    return samples


def report(samples: list[float], label: str) -> None:
    if not samples:
        print(f"\n{label}：没有拿到样本")
        return
    ordered = sorted(samples)
    p90 = ordered[min(len(ordered) - 1, int(len(ordered) * 0.9))]
    print(
        f"\n{label}（{len(samples)} 次）"
        f"  最小 {ordered[0]:.3f}s"
        f"  中位 {statistics.median(ordered):.3f}s"
        f"  p90 {p90:.3f}s"
        f"  最大 {ordered[-1]:.3f}s"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="量 JS sidecar 的冷启动耗时")
    parser.add_argument("--rounds", type=int, default=10, help="轮数，每轮一个全新进程")
    parser.add_argument("--load", type=int, default=0, help="后台占 CPU 的进程数")
    args = parser.parse_args()

    node = find_node()
    print(f"node：{node or '（没找到）'}")
    if node is None:
        print("没装 Node，量不了")
        return
    print(f"CPU 核数：{multiprocessing.cpu_count()}")

    stop = multiprocessing.Event()
    loaders = [multiprocessing.Process(target=_burn, args=(stop,)) for _ in range(args.load)]
    for process in loaders:
        process.start()
    if loaders:
        print(f"已起 {len(loaders)} 个占 CPU 的进程")

    try:
        print(f"\n量冷启动（{args.rounds} 轮）：")
        samples = asyncio.run(measure(args.rounds))
    finally:
        stop.set()
        for process in loaders:
            process.join(timeout=5)

    report(samples, "冷启动 spawn → 首次求值返回")


if __name__ == "__main__":
    main()
