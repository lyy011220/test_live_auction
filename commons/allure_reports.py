"""Allure 报告自定义工具 (参考 api_test_frame/commons/allure_reports.py)。

- set_windows_title: 替换 reports/allures/index.html 中的 "Allure Report" 为自定义标题
- get_json_data / write_json_data: 改写 reports/allures/widgets/summary.json 的 reportName
"""
import json
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_ALLURE_ROOT = _PROJECT_ROOT / "reports" / "allures"
_ALLURE_INDEX = _ALLURE_ROOT / "index.html"
_ALLURE_SUMMARY = _ALLURE_ROOT / "widgets" / "summary.json"


def set_windows_title(new_title):
    """修改 Allure 报告浏览器窗口标题 (把 "Allure Report" 替换为 new_title)。"""
    if not _ALLURE_INDEX.exists():
        return
    with open(_ALLURE_INDEX, "r+", encoding="utf-8") as f:
        lines = f.readlines()
        f.seek(0)
        f.truncate()
        for line in lines:
            f.write(line.replace("Allure Report", new_title))


def get_json_data(name):
    """读取 summary.json 并把 reportName 改为 name, 返回修改后的 dict。"""
    if not _ALLURE_SUMMARY.exists():
        return {"reportName": name}
    with open(_ALLURE_SUMMARY, "rb") as f:
        params = json.load(f)
    params["reportName"] = name
    return params


def write_json_data(data):
    """把 dict 写回 summary.json。"""
    _ALLURE_SUMMARY.parent.mkdir(parents=True, exist_ok=True)
    with open(_ALLURE_SUMMARY, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
