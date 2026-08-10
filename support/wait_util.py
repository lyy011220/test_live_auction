"""轮询等待工具: 替代固定 time.sleep, 条件满足即返回, 超时交由调用方断言。"""
from __future__ import annotations

import time


def wait_until(fetch, predicate, timeout=5.0, interval=0.3):
    """在 timeout 内每 interval 秒取 fetch() 最新值, predicate(value) 为真即提前返回。

    始终返回最后一次观测值 (超时也不抛错), 由调用方 assert 暴露期望与实际差异。

    与固定 time.sleep 的区别:
    - 条件一旦满足立即返回, 缩短用例耗时;
    - 超时返回末次观测值, 保留精确失败信息 (期望 vs 实际), 而非静默放过未收敛状态;
    - predicate 为显式 bool 判定, 避免 0/空值被当作假值而误判 (如在线人数回落到 0)。
    """
    deadline = time.monotonic() + timeout
    last = None
    while True:
        last = fetch()
        if predicate(last):
            return last
        if time.monotonic() >= deadline:
            return last
        time.sleep(interval)