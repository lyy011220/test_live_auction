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


def _parse_performance_endpoints(metrics: dict) -> dict[str, dict]:
    """按 ``{endpoint}_*`` 协议自动发现并解析性能指标。"""
    endpoints = {}
    suffix = "_requests"

    for metric_name in sorted(metrics):
        if not metric_name.endswith(suffix):
            continue

        prefix = metric_name.removesuffix(suffix)
        success_name = f"{prefix}_success_rate"
        failure_name = f"{prefix}_technical_failure_rate"
        if success_name not in metrics or failure_name not in metrics:
            continue

        requests = metrics.get(metric_name, {})
        success = metrics.get(success_name, {})
        technical_failure = metrics.get(failure_name, {})
        duration = metrics.get(f"{prefix}_success_duration", {})

        endpoint = {
            "request_count": requests.get("count"),
            "actual_rps": requests.get("rate"),
            "success_rate": success.get("value"),
            "technical_failure_rate": technical_failure.get("value"),
            "client_errors": metrics.get(f"{prefix}_4xx", {}).get("count", 0),
            "server_errors": metrics.get(f"{prefix}_5xx", {}).get("count", 0),
            "network_errors": metrics.get(
                f"{prefix}_network_errors", {}
            ).get("count", 0),
            "success_duration_p95": duration.get("p(95)"),
            "success_duration_p99": duration.get("p(99)"),
        }

        optional_metrics = {
            "accepted": (f"{prefix}_accepted", "count"),
            "business_rejections": (
                f"{prefix}_business_rejections",
                "count",
            ),
            "unexpected_rejections": (
                f"{prefix}_unexpected_rejections",
                "count",
            ),
            "handled_rate": (f"{prefix}_handled_rate", "value"),
            "handled_duration_p95": (
                f"{prefix}_handled_duration",
                "p(95)",
            ),
            "handled_duration_p99": (
                f"{prefix}_handled_duration",
                "p(99)",
            ),
            "accepted_amount_max": (
                f"{prefix}_accepted_amount",
                "max",
            ),
        }
        for output_name, (metric_name, value_name) in optional_metrics.items():
            if metric_name in metrics:
                endpoint[output_name] = metrics[metric_name].get(value_name)

        endpoints[prefix] = endpoint

    return endpoints


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
    vus_max = metrics.get("vus_max", {})
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
        "vus_max": vus_max.get("max", vus_max.get("value")),
        "dropped_iterations": metrics.get(
            "dropped_iterations", {}
        ).get("count", 0),
        "performance_endpoints": _parse_performance_endpoints(metrics),
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

    performance_endpoints = m.get("performance_endpoints") or {}
    if performance_endpoints:
        lines.extend([
            "",
            "## 接口性能指标",
            "",
            "| 接口 | 请求数 | 实际 RPS | 成功率 | 技术失败率 | "
            "成功 p95 | 成功 p99 | 4xx | 5xx | 网络错误 |",
            "| :--- | ---: | ---: | ---: | ---: | ---: | ---: | "
            "---: | ---: | ---: |",
        ])

        def number(value, suffix=""):
            if not isinstance(value, (int, float)):
                return "N/A"
            return f"{value:.2f}{suffix}"

        def percent(value):
            if not isinstance(value, (int, float)):
                return "N/A"
            return f"{value * 100:.2f}%"

        for endpoint, values in sorted(performance_endpoints.items()):
            lines.append(
                f"| {endpoint} "
                f"| {values.get('request_count', 'N/A')} "
                f"| {number(values.get('actual_rps'))} "
                f"| {percent(values.get('success_rate'))} "
                f"| {percent(values.get('technical_failure_rate'))} "
                f"| {number(values.get('success_duration_p95'), 'ms')} "
                f"| {number(values.get('success_duration_p99'), 'ms')} "
                f"| {values.get('client_errors', 0)} "
                f"| {values.get('server_errors', 0)} "
                f"| {values.get('network_errors', 0)} |"
            )

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


def capacity_to_markdown(manifest: dict) -> str:
    """将多档容量运行清单渲染为对比报告。"""
    is_bid_capacity = manifest.get("scenario") == "bid_capacity"
    title = (
        "单竞拍热点出价容量测试"
        if is_bid_capacity
        else "竞拍详情容量测试"
    )
    lines = [
        f"# {title}",
        "",
        f"- 运行 ID: {manifest.get('run_id')}",
        f"- 竞拍 ID: {manifest.get('auction_id')}",
        f"- 目标后端: {manifest.get('base_url')}",
        f"- 单档时长: {manifest.get('duration')}",
        f"- 冷却时间: {manifest.get('cooldown_seconds')} 秒",
        "",
        "| 目标 RPS | 实际 RPS | "
        + ("接受率 | " if is_bid_capacity else "成功率 | ")
        + "技术失败率 | "
        + ("处理 p95 | 处理 p99 | " if is_bid_capacity else "成功 p95 | 成功 p99 | ")
        + "4xx | 5xx | 网络错误 | "
        "丢弃迭代 | 最大 VU | "
        + (
            "接受数 | 竞争拒绝 | 非预期拒绝 | 处理率 | 最高接受价 | "
            if is_bid_capacity
            else ""
        )
        + "结果 | 原因 |",
        "| ---: | ---: | ---: | ---: | ---: | ---: | "
        "---: | ---: | ---: | ---: | ---: | "
        + (
            "---: | ---: | ---: | ---: | ---: | "
            if is_bid_capacity
            else ""
        )
        + ":--- | :--- |",
    ]

    def number(value, suffix=""):
        if not isinstance(value, (int, float)):
            return "N/A"
        return f"{value:.2f}{suffix}"

    def percent(value):
        if not isinstance(value, (int, float)):
            return "N/A"
        return f"{value * 100:.2f}%"

    for stage in manifest.get("stages", []):
        metrics = stage.get("metrics") or {}
        duration_p95 = metrics.get(
            "handled_duration_p95"
            if is_bid_capacity
            else "success_duration_p95"
        )
        duration_p99 = metrics.get(
            "handled_duration_p99"
            if is_bid_capacity
            else "success_duration_p99"
        )
        outcome_columns = ""
        if is_bid_capacity:
            outcome_columns = (
                f"| {metrics.get('accepted', 'N/A')} "
                f"| {metrics.get('business_rejections', 'N/A')} "
                f"| {metrics.get('unexpected_rejections', 'N/A')} "
                f"| {percent(metrics.get('handled_rate'))} "
                f"| {number(metrics.get('accepted_amount_max'))} "
            )
        lines.append(
            f"| {stage.get('target_rps')} "
            f"| {number(metrics.get('actual_rps'))} "
            f"| {percent(metrics.get('success_rate'))} "
            f"| {percent(metrics.get('technical_failure_rate'))} "
            f"| {number(duration_p95, 'ms')} "
            f"| {number(duration_p99, 'ms')} "
            f"| {metrics.get('client_errors', 'N/A')} "
            f"| {metrics.get('server_errors', 'N/A')} "
            f"| {metrics.get('network_errors', 'N/A')} "
            f"| {metrics.get('dropped_iterations', 'N/A')} "
            f"| {metrics.get('vus_max', 'N/A')} "
            f"{outcome_columns}"
            f"| {stage.get('assessment')} "
            f"| {', '.join(stage.get('reasons') or []) or '-'} |"
        )

    not_run = manifest.get("not_run_rates") or []
    if not_run:
        lines.extend([
            "",
            f"- 未执行档位: {', '.join(str(rate) for rate in not_run)} RPS",
        ])
    return "\n".join(lines)


def write_capacity_markdown(run_dir: Path, manifest: dict) -> Path:
    path = run_dir / "summary.md"
    path.write_text(capacity_to_markdown(manifest), encoding="utf-8")
    info_log(f"容量对比摘要已写入: {path}")
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
    from load.concurrency.registry import (
        scenario_by_case_id as concurrency_scenario_by_case_id,
    )
    from load.performance.registry import (
        scenario_by_case_id as performance_scenario_by_case_id,
    )

    s = (
        concurrency_scenario_by_case_id(case_id)
        or performance_scenario_by_case_id(case_id)
    )
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
