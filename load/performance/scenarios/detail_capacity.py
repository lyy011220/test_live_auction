"""竞拍详情固定 RPS 容量场景。"""
from __future__ import annotations

from pathlib import Path

from load.performance.capacity import CapacityOptions, run_capacity_k6
from load.shared.execution import cleanup, prepare


def assess_detail_stage(
    *,
    metrics: dict,
    target_rps: int,
    baseline_p95: float | None,
    k6_exit_code: int,
) -> tuple[str, list[str]]:
    required = (
        "actual_rps",
        "success_rate",
        "technical_failure_rate",
        "success_duration_p95",
    )
    if any(not isinstance(metrics.get(name), (int, float)) for name in required):
        return "STOP", ["missing_required_metrics"]
    if metrics.get("client_errors", 0) > 0:
        return "STOP", ["client_errors_detected"]

    technical_failure = metrics["technical_failure_rate"]
    if technical_failure >= 0.10:
        return "STOP", ["technical_failure_safety_limit"]

    reasons = []
    if metrics["actual_rps"] < target_rps * 0.99:
        reasons.append("actual_rps_below_99_percent")
    if metrics["success_rate"] < 0.99:
        reasons.append("success_rate_below_99_percent")
    if technical_failure >= 0.01:
        reasons.append("technical_failure_at_least_1_percent")
    if metrics.get("dropped_iterations", 0) != 0:
        reasons.append("dropped_iterations")
    if baseline_p95 is not None and (
        metrics["success_duration_p95"] > baseline_p95 * 2
    ):
        reasons.append("p95_above_twice_baseline")
    if k6_exit_code != 0:
        reasons.append(f"k6_exit_code_{k6_exit_code}")
    return ("KNEE", reasons) if reasons else ("PASS", [])


def run_detail_capacity(
    *,
    scenario,
    password: str,
    base_url: str,
    k6_bin: str,
    options: CapacityOptions,
    health_check=None,
    keep_artifacts: bool = False,
) -> tuple[int, Path]:
    del keep_artifacts
    ctx, _tokens = prepare(scenario, password)
    auction_id = ctx["auctionId"]
    room_id = ctx["roomId"]
    try:
        return run_capacity_k6(
            scenario=scenario,
            auction_id=auction_id,
            room_id=room_id,
            base_url=base_url,
            k6_bin=k6_bin,
            options=options,
            health_check=health_check,
            metric_prefix="detail",
            assessor=assess_detail_stage,
        )
    finally:
        cleanup(ctx, auction_id, room_id)
