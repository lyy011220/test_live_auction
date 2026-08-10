"""框架运行入口 (参考 api_test_frame/run.py)。

执行 pytest 后, 按 config.yaml 的 REPORT_TYPE 生成报告:
- allure: 复制 environment.xml/categories.json 到 reports/temps, allure generate 到 reports/allures,
          并自定义报告标题 (index.html + widgets/summary.json)。
"""
import shutil
import subprocess
from pathlib import Path

import pytest

from commons.allure_reports import set_windows_title, get_json_data, write_json_data
from commons.logger_util import info_log
from commons.yaml_util import read_config

REPORT_TITLE = "直播竞拍平台测试报告"
PROJECT_ROOT = Path(__file__).resolve().parent
REPORTS_ROOT = PROJECT_ROOT / "reports"
ALLURE_RESULTS = REPORTS_ROOT / "temps"
ALLURE_REPORT = REPORTS_ROOT / "allures"


def run_allure_report() -> int:
    """生成 allure 报告并自定义标题, 返回 Allure 进程退出码。"""
    ALLURE_RESULTS.mkdir(parents=True, exist_ok=True)
    # 复制环境信息与失败分类到 allure 原始结果目录
    for name in ("environment.xml", "categories.json"):
        source = PROJECT_ROOT / name
        if source.exists():
            shutil.copy(source, ALLURE_RESULTS)
    # 生成静态 html 报告
    try:
        result = subprocess.run(
            ["allure", "generate", str(ALLURE_RESULTS), "-o", str(ALLURE_REPORT), "--clean"],
            check=False,
            cwd=PROJECT_ROOT,
        )
    except OSError as exc:
        info_log(f"Allure 命令执行失败: {exc}")
        return 127
    if result.returncode != 0:
        info_log(f"Allure 报告生成失败, 退出码: {result.returncode}")
        return result.returncode
    # 自定义浏览器窗口标题 (替换 index.html 中的 "Allure Report")
    set_windows_title(REPORT_TITLE)
    # 自定义报告名称 (写 widgets/summary.json 的 reportName)
    report_title = get_json_data(REPORT_TITLE)
    write_json_data(report_title)
    info_log("Allure 报告已生成: reports\\allures\\index.html")
    return 0


def main() -> int:
    """执行测试与报告生成, 确保任一阶段失败都会返回非零退出码。"""
    pytest_exit = int(pytest.main([str(PROJECT_ROOT / "tests")]))
    report_exit = 0
    report_type = read_config("REPORT_TYPE")
    if report_type == "allure":
        report_exit = run_allure_report()
    else:
        info_log(f"未知的报告类型: {report_type}")
        report_exit = 2
    final_exit = pytest_exit or report_exit
    info_log(f"接口自动化测试完成, 退出码: {final_exit}")
    return final_exit


if __name__ == "__main__":
    raise SystemExit(main())
