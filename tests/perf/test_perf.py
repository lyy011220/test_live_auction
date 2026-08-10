"""PERF 域 | 并发负载场景 (k6 调度, pytest 内做结果校验与 Allure 挂载)。

覆盖 5 例: PERF-LOAD-001~004, PERF-STRESS-001。
- LOAD-001/002/003: REST 并发出价 (乱序金额 / 同价竞争 / 多轮)。
- LOAD-004: STOMP-over-WebSocket 并发出价 (ws_bid_concurrent)。
- STRESS-001: 50 VU 混合场景 5 分钟稳定性 (mixed_stress)。

工作流:
1. CLI 运行 k6:  python -m load.runner --scenario bid_concurrent
   -> 产出 reports/k6/{scenario}.json (k6 summary) + .md (摘要)
2. pytest 收集本模块: 若对应 k6 summary 存在, 则 attach 到 Allure 并校验
   checks 无失败 / 无 5xx; 否则 skip 并提示先跑 k6。

这样 PERF 用例在追溯矩阵中为 implemented, 并在 Allure 报告中呈现 k6 指标。
"""
import allure
import pytest

from load.summarize import SummaryValidationError, attach_allure, load_summary_by_case_id
from support.traceability import case

EPIC = allure.epic("直播竞拍平台")
FEATURE = allure.feature("性能域")


def _require_k6_summary(case_id: str):
    """加载 k6 summary; 不存在则 skip, 存在则 attach 到 Allure。"""
    try:
        summary = load_summary_by_case_id(case_id)
    except SummaryValidationError as exc:
        pytest.fail(str(exc), pytrace=False)
    if summary is None:
        pytest.skip(f"未运行 k6, 请先执行: python -m load.runner --scenario <对应场景>")
    attach_allure(case_id, summary)
    return summary


def _assert_load_summary(summary: dict, minimum_iterations: int) -> None:
    """负载场景共用的完整性与稳定性断言。"""
    assert summary["state"] is False, "k6 threshold 状态不应失败"
    assert summary["checks_fails"] == 0, f"k6 checks 存在失败: {summary['checks_fails']}"
    assert summary["checks_rate"] == 1, f"k6 checks 通过率应为 100%, 实际 {summary['checks_rate']}"
    assert (summary["http_req_failed_rate"] or 0) == 0, "不应出现 5xx 或网络错误"
    assert summary["http_req_duration_p95"] is not None, "k6 摘要缺少 HTTP p95"
    assert summary["http_req_duration_p95"] < 1000, (
        f"HTTP p95 应 < 1000ms, 实际 {summary['http_req_duration_p95']}ms"
    )
    assert (summary["iterations"] or 0) >= minimum_iterations, (
        f"迭代次数至少 {minimum_iterations}, 实际 {summary['iterations']}"
    )


@EPIC
@FEATURE
@allure.story("PERF-LOAD-001")
@allure.severity(allure.severity_level.NORMAL)
@allure.title("PERF-LOAD-001 二十人乱序不同金额并发 (k6)")
@pytest.mark.perf
@pytest.mark.load
@case("PERF-LOAD-001")
def test_perf_load_001_twenty_vu_mixed():
    """核心预期: 全部设计请求可执行且最终唯一最高价 300、无回退。"""
    m = _require_k6_summary("PERF-LOAD-001")
    _assert_load_summary(m, 20)


@EPIC
@FEATURE
@allure.story("PERF-LOAD-002")
@allure.severity(allure.severity_level.NORMAL)
@allure.title("PERF-LOAD-002 五人同时同价竞价 (k6)")
@pytest.mark.perf
@pytest.mark.load
@case("PERF-LOAD-002")
def test_perf_load_002_five_vu_same_amount():
    """核心预期: 仅一个请求成为有效最高出价且无服务端异常。"""
    m = _require_k6_summary("PERF-LOAD-002")
    _assert_load_summary(m, 5)


@EPIC
@FEATURE
@allure.story("PERF-LOAD-003")
@allure.severity(allure.severity_level.NORMAL)
@allure.title("PERF-LOAD-003 重复多轮并发与最终投影一致性 (k6)")
@pytest.mark.perf
@pytest.mark.load
@case("PERF-LOAD-003")
def test_perf_load_003_repeat_rounds():
    """核心预期: 多轮请求无服务端异常，终价、排行榜和 bidCount 最终投影一致。"""
    m = _require_k6_summary("PERF-LOAD-003")
    _assert_load_summary(m, 15)


@EPIC
@FEATURE
@allure.story("PERF-LOAD-004")
@allure.severity(allure.severity_level.NORMAL)
@allure.title("PERF-LOAD-004 二十人 WebSocket 并发出价 (k6)")
@pytest.mark.perf
@pytest.mark.load
@case("PERF-LOAD-004")
def test_perf_load_004_ws_concurrent():
    """核心预期: 20 VU 完成订阅、发送出价并收到后续 BID 广播，广播 p95 < 2s，终价 == max。"""
    m = _require_k6_summary("PERF-LOAD-004")
    _assert_load_summary(m, 20)
    assert m["ws_bid_broadcast_p95"] is not None, "k6 摘要缺少 WS 广播 p95"
    assert m["ws_bid_broadcast_p95"] < 2000, (
        f"WS 出价后广播 p95 应 < 2000ms, 实际 {m['ws_bid_broadcast_p95']}ms"
    )


@EPIC
@FEATURE
@allure.story("PERF-STRESS-001")
@allure.severity(allure.severity_level.CRITICAL)
@allure.title("PERF-STRESS-001 五十人混合场景稳定性 (k6)")
@pytest.mark.perf
@pytest.mark.stress
@case("PERF-STRESS-001")
def test_perf_stress_001_mixed_scenario():
    """核心预期: 50 VU 混合操作 (首轮流式出价 + 持续读详情/排行榜) 5 分钟, 无网络错误,
    5xx 错误率 < 1%, 服务端不崩溃 (teardown 详情仍 200)。"""
    m = _require_k6_summary("PERF-STRESS-001")
    assert m["state"] is False, "k6 threshold 状态不应失败"
    assert (m["checks_rate"] or 0) > 0.99, f"checks 通过率应 > 99%, 实际 {m['checks_rate']}"
    assert (m["http_req_failed_rate"] or 0) < 0.01, (
        f"5xx 错误率 {m['http_req_failed_rate']} 应 < 1%"
    )
    assert m["http_req_duration_p95"] is not None, "k6 摘要缺少 HTTP p95"
    assert m["http_req_duration_p95"] < 1000, (
        f"HTTP p95 应 < 1000ms, 实际 {m['http_req_duration_p95']}ms"
    )
    assert (m["iterations"] or 0) >= 1000, f"5 分钟压测应产生大量迭代, 实际 {m['iterations']}"
