"""有限并发正确性场景：关注竞争结果，不用于推导系统容量。"""

import allure
import pytest

from support.traceability import case
from tests.fixtures.k6_results import (
    assert_concurrency_load_summary,
    require_k6_summary,
)

EPIC = allure.epic("直播竞拍平台")
FEATURE = allure.feature("并发正确性")


@EPIC
@FEATURE
@allure.story("PERF-LOAD-001")
@allure.severity(allure.severity_level.NORMAL)
@allure.title("PERF-LOAD-001 二十人乱序不同金额并发 (k6)")
@pytest.mark.concurrency
@pytest.mark.load
@case("PERF-LOAD-001")
def test_k6_concurrency_001_twenty_vu_mixed():
    """全部请求被处理，最终价格由唯一最高有效出价决定。"""
    summary = require_k6_summary("PERF-LOAD-001")
    assert_concurrency_load_summary(summary, 20)


@EPIC
@FEATURE
@allure.story("PERF-LOAD-002")
@allure.severity(allure.severity_level.NORMAL)
@allure.title("PERF-LOAD-002 五人同时同价竞价 (k6)")
@pytest.mark.concurrency
@pytest.mark.load
@case("PERF-LOAD-002")
def test_k6_concurrency_002_five_vu_same_amount():
    """同价竞争只有一个请求成为有效最高出价。"""
    summary = require_k6_summary("PERF-LOAD-002")
    assert_concurrency_load_summary(summary, 5)


@EPIC
@FEATURE
@allure.story("PERF-LOAD-003")
@allure.severity(allure.severity_level.NORMAL)
@allure.title("PERF-LOAD-003 重复多轮并发与最终投影一致性 (k6)")
@pytest.mark.concurrency
@pytest.mark.load
@case("PERF-LOAD-003")
def test_k6_concurrency_003_repeat_rounds():
    """多轮请求后终价、排行榜和 bidCount 投影一致。"""
    summary = require_k6_summary("PERF-LOAD-003")
    assert_concurrency_load_summary(summary, 15)


@EPIC
@FEATURE
@allure.story("PERF-LOAD-004")
@allure.severity(allure.severity_level.NORMAL)
@allure.title("PERF-LOAD-004 二十人 WebSocket 并发出价 (k6)")
@pytest.mark.concurrency
@pytest.mark.load
@case("PERF-LOAD-004")
def test_k6_concurrency_004_ws_concurrent():
    """并发订阅和出价后收到 BID 广播，且广播延迟满足阈值。"""
    summary = require_k6_summary("PERF-LOAD-004")
    assert_concurrency_load_summary(summary, 20)
    assert summary["ws_bid_broadcast_p95"] is not None, (
        "k6 摘要缺少 WS 广播 p95"
    )
    assert summary["ws_bid_broadcast_p95"] < 2000, (
        "WS 出价后广播 p95 应 < 2000ms, "
        f"实际 {summary['ws_bid_broadcast_p95']}ms"
    )
