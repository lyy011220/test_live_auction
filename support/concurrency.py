"""并发支持: ConcurrentRunner 用 Barrier 同时释放, 捕获每线程结果。"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Callable


@dataclass
class ThreadResult:
    success: bool = False
    http_status: int | None = None
    biz_code: object = None
    data: dict = field(default_factory=dict)
    exception: Exception | None = None


class ConcurrentRunner:
    """线程化并发执行器: barrier 保证同时起跑, 捕获每个线程结果。"""

    def __init__(self, workers: list[Callable[[], ThreadResult]], timeout: float = 30.0):
        self.workers = workers
        self.results: list[ThreadResult] = [ThreadResult() for _ in workers]
        self.timeout = timeout
        self._barrier = threading.Barrier(len(workers), timeout=10)

    def _run(self, idx: int, fn: Callable[[], ThreadResult]) -> None:
        try:
            self._barrier.wait()
            self.results[idx] = fn()
        except Exception as exc:  # noqa: BLE001
            self.results[idx] = ThreadResult(exception=exc)

    def spawn(self) -> list[ThreadResult]:
        threads = [
            threading.Thread(target=self._run, args=(i, fn), daemon=True)
            for i, fn in enumerate(self.workers)
        ]
        for t in threads:
            t.start()
        deadline = time.monotonic() + self.timeout
        for t in threads:
            remaining = max(0.0, deadline - time.monotonic())
            t.join(timeout=remaining)
        for idx, thread in enumerate(threads):
            if thread.is_alive():
                self.results[idx] = ThreadResult(
                    exception=TimeoutError(
                        f"并发 worker {idx} 在 {self.timeout:g}s 内未结束"
                    )
                )
        # 后台 daemon 即使稍后结束，也不得再改变调用方已经收到的判定结果。
        return list(self.results)


def assert_exactly_one_succeeded(results: list[ThreadResult]) -> ThreadResult:
    ok = [r for r in results if r.success]
    assert len(ok) == 1, f"期望恰好一个成功, 实际 {len(ok)}: {results}"
    return ok[0]


def failed(results: list[ThreadResult]) -> list[ThreadResult]:
    return [r for r in results if not r.success]
