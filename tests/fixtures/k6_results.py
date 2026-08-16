"""k6 结果加载与公共断言，供并发正确性和性能测试复用。"""

import pytest

from load.summarize import (
    SummaryValidationError,
    attach_allure,
    load_summary_by_case_id,
)


def require_k6_summary(case_id: str) -> dict:
    """加载并挂载 k6 summary；场景尚未运行时跳过验收。"""
    try:
        summary = load_summary_by_case_id(case_id)
    except SummaryValidationError as exc:
        pytest.fail(str(exc), pytrace=False)
    if summary is None:
        pytest.skip(
            "未运行 k6，请先执行: "
            "python -m load.<concurrency|performance>.runner --scenario <对应场景>"
        )
    attach_allure(case_id, summary)
    return summary


def assert_concurrency_load_summary(
    summary: dict,
    minimum_iterations: int,
) -> None:
    """断言有限并发场景执行完整且业务检查全部通过。"""
    assert summary["state"] is False, "k6 threshold 状态不应失败"
    assert summary["checks_fails"] == 0, (
        f"k6 checks 存在失败: {summary['checks_fails']}"
    )
    assert summary["checks_rate"] == 1, (
        f"k6 checks 通过率应为 100%, 实际 {summary['checks_rate']}"
    )
    assert (summary["http_req_failed_rate"] or 0) == 0, (
        "不应出现 5xx 或网络错误"
    )
    assert summary["http_req_duration_p95"] is not None, (
        "k6 摘要缺少 HTTP p95"
    )
    assert summary["http_req_duration_p95"] < 1000, (
        "HTTP p95 应 < 1000ms, "
        f"实际 {summary['http_req_duration_p95']}ms"
    )
    assert (summary["iterations"] or 0) >= minimum_iterations, (
        f"迭代次数至少 {minimum_iterations}, "
        f"实际 {summary['iterations']}"
    )
