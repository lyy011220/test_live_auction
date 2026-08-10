"""顶层 conftest
- session banner
- pytest_terminal_summary: 收集统计写 reports/result.txt
- pytest_runtest_makereport: 失败时 attach 堆栈
- pytest_sessionfinish: 生成 reports/traceability.md
"""
import os
import time
from decimal import Decimal
from pathlib import Path

import allure
import pytest

from commons.logger_util import info_log
from commons.yaml_util import read_config
from support.traceability import CASES, discover_cases, dump_traceability

PROJECT_ROOT = Path(__file__).resolve().parent
REPORTS_ROOT = PROJECT_ROOT / "reports"


def pytest_configure(config):
    """无论从哪个目录启动 pytest，都把 Allure 原始结果固定到项目 reports。"""
    if hasattr(config.option, "allure_report_dir"):
        config.option.allure_report_dir = str(REPORTS_ROOT / "temps")


@pytest.fixture(scope="session", autouse=True)
def _session_banner():
    project = read_config("project_name") or "live_auction_qa"
    info_log("-" * 80)
    info_log(f"{project} 开始执行")
    info_log("-" * 80)
    yield
    info_log("-" * 80)
    info_log("接口自动化测试结束")
    info_log("-" * 80)


@pytest.fixture(scope="session", autouse=True)
def _record_start(request):
    request.config._qa_start_time = time.time()
    yield


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    if report.when == "call" and report.failed:
        allure.attach(str(report.longreprtext), "失败堆栈", allure.attachment_type.TEXT)


def _is_collect_only(config):
    return bool(getattr(getattr(config, "option", None), "collectonly", False))


def pytest_sessionfinish(session, exitstatus):
    if _is_collect_only(session.config):
        return
    try:
        full_cases = discover_cases(PROJECT_ROOT / "tests")
        dump_traceability(
            REPORTS_ROOT / "traceability.md",
            cases=full_cases,
            title="完整用例追溯矩阵",
        )
        dump_traceability(
            REPORTS_ROOT / "traceability-current.md",
            cases=CASES,
            title="本次执行用例追溯矩阵",
        )
    except Exception as exc:  # pragma: no cover
        info_log(f"traceability 写入失败: {exc}")


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    if _is_collect_only(config):
        return
    case_total = getattr(terminalreporter, "_numcollected", 0) or 0
    if case_total <= 0:
        return
    passed = len(terminalreporter.stats.get("passed", []))
    failed = len(terminalreporter.stats.get("failed", []))
    skipped = len(terminalreporter.stats.get("skipped", []))
    error = len(terminalreporter.stats.get("error", []))
    start = getattr(config, "_qa_start_time", None) or time.time()
    duration = Decimal(time.time() - start).quantize(Decimal("0.00"))
    rate = Decimal(passed / case_total * 100).quantize(Decimal("0.00"))

    os.makedirs(REPORTS_ROOT, exist_ok=True)
    result = REPORTS_ROOT / "result.txt"
    with open(result, "w", encoding="utf-8") as f:
        f.write("测试用例总数：%s个\n" % case_total)
        f.write("通过数：%s个\n" % passed)
        f.write("失败数：%s个\n" % failed)
        f.write("跳过数：%s个\n" % skipped)
        f.write("错误数：%s个\n" % error)
        f.write("测试用例执行时长：%s秒\n" % duration)
        f.write("成功率：%s%%\n" % rate)
