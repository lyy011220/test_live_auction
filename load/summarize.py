"""k6 结果摘要: 解析 --summary-export JSON -> 结构化指标 + Markdown + Allure 附件。

- runner.py 调用 write_markdown 落盘 reports/k6/{scenario}.md
- tests/perf 调用 attach_allure / load_summary_by_case_id 把 k6 指标挂到 Allure
"""
from __future__ import annotations

import json
from pathlib import Path

from commons.logger_util import info_log
from load.provenance import (
    SummaryValidationError,
    metadata_path_for,
    validate_run_metadata,
)

REPORTS_K6 = Path(__file__).resolve().parents[1] / "reports" / "k6"


def summary_path_for(scenario_name: str) -> Path:
    return REPORTS_K6 / f"{scenario_name}.json"


def parse(summary_path: Path) -> dict:
    """从 k6 summary JSON 提取关键指标。

    k6 v2.x summary 结构: rate 类指标的比率在 `value` 字段 (非 `rate`),
    trend 类指标的 p(95)/avg 为顶层键, iterations.count 为顶层键。
    """
    with open(summary_path, encoding="utf-8") as f:
        data = json.load(f)
    metrics = data.get("metrics", {})
    checks = metrics.get("checks", {})
    http_failed = metrics.get("http_req_failed", {})
    duration = metrics.get("http_req_duration", {})
    iter_duration = metrics.get("iteration_duration", {})
    ws_bid_broadcast = metrics.get("ws_bid_broadcast_ms", {})
    return {
        "scenario": data.get("root_group", {}).get("name", ""),
        "state": data.get("state", {}).get("isFailed", False),
        "checks_rate": checks.get("value"),
        "checks_passes": checks.get("passes", 0),
        "checks_fails": checks.get("fails", 0),
        "http_req_failed_rate": http_failed.get("value"),
        "http_req_duration_p95": duration.get("p(95)"),
        "http_req_duration_avg": duration.get("avg"),
        # iteration_duration 覆盖每次 default() 全程 (含 WS 连接+订阅+发送+等待广播),
        # 是 WS 场景的往返时延指标 (http_req_duration 仅统计 http.* 请求, 不含 WS 帧)。
        "iteration_duration_p95": iter_duration.get("p(95)"),
        "ws_bid_broadcast_p95": ws_bid_broadcast.get("p(95)"),
        "iterations": metrics.get("iterations", {}).get("count"),
        "vus_max": metrics.get("vus", {}).get("max"),
    }


def to_markdown(m: dict) -> str:
    rate = m.get("checks_rate")
    rate_str = f"{rate * 100:.2f}%" if isinstance(rate, (int, float)) else "N/A"
    p95 = m.get("http_req_duration_p95")
    p95_str = f"{p95:.2f}ms" if isinstance(p95, (int, float)) else "N/A"
    avg = m.get("http_req_duration_avg")
    avg_str = f"{avg:.2f}ms" if isinstance(avg, (int, float)) else "N/A"
    iter_p95 = m.get("iteration_duration_p95")
    iter_p95_str = f"{iter_p95:.2f}ms" if isinstance(iter_p95, (int, float)) else "N/A"
    ws_p95 = m.get("ws_bid_broadcast_p95")
    ws_p95_str = f"{ws_p95:.2f}ms" if isinstance(ws_p95, (int, float)) else "N/A"
    failed = m.get("http_req_failed_rate")
    failed_str = f"{failed * 100:.2f}%" if isinstance(failed, (int, float)) else "N/A"
    lines = [
        "# k6 性能结果摘要",
        "",
        f"- 场景: {m.get('scenario')}",
        f"- 是否失败: {m.get('state')}",
        f"- checks 通过率: {rate_str} (passes={m.get('checks_passes')}, fails={m.get('checks_fails')})",
        f"- HTTP 失败率(5xx/网络): {failed_str}",
        f"- 响应耗时 p95: {p95_str} / avg: {avg_str}",
        f"- 迭代耗时 p95 (含 WS 往返): {iter_p95_str}",
        f"- WS 出价后广播耗时 p95: {ws_p95_str}",
        f"- 迭代次数: {m.get('iterations')}",
        f"- 最大并发 VU: {m.get('vus_max')}",
    ]
    run = m.get("run") or {}
    if run:
        lines.extend([
            f"- 运行完成时间: {run.get('completed_at')}",
            f"- 目标后端: {run.get('base_url')}",
            f"- 后端版本: {(run.get('backend') or {}).get('configured_version') or (run.get('backend') or {}).get('api_version')}",
            f"- OpenAPI SHA-256: {(run.get('backend') or {}).get('openapi_sha256')}",
        ])
    return "\n".join(lines)


def write_markdown(scenario_name: str, m: dict) -> Path:
    REPORTS_K6.mkdir(parents=True, exist_ok=True)
    path = REPORTS_K6 / f"{scenario_name}.md"
    path.write_text(to_markdown(m), encoding="utf-8")
    info_log(f"k6 摘要已写入: {path}")
    return path


def attach_allure(case_id: str, m: dict) -> None:
    """把 k6 指标挂到当前 Allure 测试 (仅在 pytest 上下文生效)。"""
    try:
        import allure

        allure.attach(to_markdown(m), f"{case_id} k6 摘要", allure.attachment_type.TEXT)
        allure.attach(
            json.dumps(m, ensure_ascii=False, indent=2),
            f"{case_id} k6 指标", allure.attachment_type.JSON,
        )
    except Exception as exc:  # noqa: BLE001
        info_log(f"Allure attach 跳过 (非 pytest 上下文): {exc}")


def load_summary_by_case_id(case_id: str) -> dict | None:
    """按 case_id 反查场景, 若 k6 summary 存在则返回解析后的指标, 否则 None。"""
    from load.registry import scenario_by_case_id

    s = scenario_by_case_id(case_id)
    if s is None:
        return None
    path = summary_path_for(s.name)
    if not path.exists():
        return None
    metadata_path = metadata_path_for(s.name)
    if not metadata_path.exists():
        raise SummaryValidationError(f"{s.name} 缺少运行元数据，现有 JSON 属于旧格式，请重新运行")
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SummaryValidationError(f"{s.name} 运行元数据损坏，请重新运行") from exc
    validate_run_metadata(s.name, metadata)
    summary = parse(path)
    summary["run"] = metadata
    return summary
