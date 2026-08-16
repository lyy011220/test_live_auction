"""性能稳定性场景：关注持续混合负载下的错误率和延迟。"""

import allure
import pytest

from support.traceability import case
from tests.fixtures.k6_results import require_k6_summary

EPIC = allure.epic("直播竞拍平台")
FEATURE = allure.feature("性能域")


@EPIC
@FEATURE
@allure.story("PERF-STRESS-001")
@allure.severity(allure.severity_level.CRITICAL)
@allure.title("PERF-STRESS-001 五十人混合场景稳定性 (k6)")
@pytest.mark.perf
@pytest.mark.stress
@case("PERF-STRESS-001")
def test_perf_stress_001_mixed_scenario():
    """持续混合操作时错误率和响应延迟保持在阈值内。"""
    summary = require_k6_summary("PERF-STRESS-001")
    assert summary["state"] is False, "k6 threshold 状态不应失败"
    assert (summary["checks_rate"] or 0) > 0.99, (
        f"checks 通过率应 > 99%, 实际 {summary['checks_rate']}"
    )
    assert (summary["http_req_failed_rate"] or 0) < 0.01, (
        f"5xx 错误率 {summary['http_req_failed_rate']} 应 < 1%"
    )
    assert summary["http_req_duration_p95"] is not None, (
        "k6 摘要缺少 HTTP p95"
    )
    assert summary["http_req_duration_p95"] < 1000, (
        "HTTP p95 应 < 1000ms, "
        f"实际 {summary['http_req_duration_p95']}ms"
    )
    assert (summary["iterations"] or 0) >= 1000, (
        "5 分钟压测应产生大量迭代, "
        f"实际 {summary['iterations']}"
    )
