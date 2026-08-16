"""单竞拍热点出价容量场景。"""
from __future__ import annotations

import json
import shutil
import tempfile
from collections.abc import Callable, Mapping
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from clients.auction_client import AuctionClient
from commons.logger_util import info_log
from load.performance.capacity import (
    CapacityOptions,
    default_max_vus,
    default_preallocated_vus,
    run_capacity_k6,
)
from load.shared.execution import cleanup, generate_tokens
from models.enums import AuctionStatus
from scenarios.auction_lifecycle import AuctionLifecycle


BID_START_PRICE = 100
BID_INCREMENT_AMOUNT = 1
BID_MAX_PRICE = 1_000_000


def _decimal(value: Any) -> Decimal | None:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def validate_bid_snapshot(
    *,
    metrics: dict,
    detail: dict,
) -> list[str]:
    reasons = []
    accepted = metrics.get("accepted")
    accepted_amount_max = _decimal(metrics.get("accepted_amount_max"))
    bid_count = detail.get("bidCount")
    current_price = _decimal(detail.get("currentPrice"))

    if detail.get("status") != AuctionStatus.LIVE:
        reasons.append("auction_not_live")
    if not isinstance(accepted, (int, float)) or bid_count != accepted:
        reasons.append("bid_count_mismatch")
    if accepted_amount_max is None or current_price != accepted_amount_max:
        reasons.append("current_price_mismatch")
    return reasons


def assess_bid_stage(
    *,
    metrics: dict,
    target_rps: int,
    baseline_p95: float | None,
    k6_exit_code: int,
) -> tuple[str, list[str]]:
    required = (
        "actual_rps",
        "technical_failure_rate",
        "handled_rate",
        "unexpected_rejections",
        "handled_duration_p95",
    )
    if any(not isinstance(metrics.get(name), (int, float)) for name in required):
        return "STOP", ["missing_required_metrics"]

    reasons = []
    must_stop = False
    if metrics["unexpected_rejections"] > 0:
        reasons.append("unexpected_rejections_detected")
        must_stop = True

    technical_failure = metrics["technical_failure_rate"]
    if technical_failure >= 0.10:
        reasons.append("technical_failure_safety_limit")
        must_stop = True

    if metrics["actual_rps"] < target_rps * 0.99:
        reasons.append("actual_rps_below_99_percent")
    if metrics["handled_rate"] < 0.99:
        reasons.append("handled_rate_below_99_percent")
    if 0.01 <= technical_failure < 0.10:
        reasons.append("technical_failure_at_least_1_percent")
    if metrics.get("dropped_iterations", 0) != 0:
        reasons.append("dropped_iterations")
    if baseline_p95 is not None and (
        metrics["handled_duration_p95"] > baseline_p95 * 2
    ):
        reasons.append("p95_above_twice_baseline")
    if k6_exit_code != 0:
        reasons.append(f"k6_exit_code_{k6_exit_code}")
    if must_stop:
        return "STOP", reasons
    return ("KNEE", reasons) if reasons else ("PASS", [])


def create_bid_stage(password: str, target_rps: int) -> dict:
    resource = AuctionLifecycle(password=password).create_started_auction(
        name=f"load-bid-capacity-{target_rps}rps",
        startPrice=BID_START_PRICE,
        incrementAmount=BID_INCREMENT_AMOUNT,
        maxPrice=BID_MAX_PRICE,
        durationMinutes=20,
    )
    return {
        "auction_id": resource["auctionId"],
        "room_id": resource["roomId"],
        "resource": resource,
    }


def cleanup_bid_stage(context: Mapping) -> None:
    resource = context["resource"]
    cleanup(resource, context["auction_id"], context["room_id"])


def validate_bid_stage(context: Mapping, metrics: dict) -> list[str]:
    resource = context["resource"]
    client = AuctionClient(resource["merchantClient"])
    try:
        detail_response = client.public_detail(context["auction_id"])
        if not detail_response.is_ok:
            return ["detail_query_failed"]
    except Exception:  # noqa: BLE001
        return ["state_validation_error"]

    detail = detail_response.data or {}
    if not isinstance(detail, dict):
        return ["state_payload_invalid"]
    return validate_bid_snapshot(
        metrics=metrics,
        detail=detail,
    )


def run_bid_hotspot_capacity(
    *,
    scenario,
    password: str,
    base_url: str,
    k6_bin: str,
    options: CapacityOptions,
    health_check=None,
    keep_artifacts: bool = False,
    token_provider: Callable[[int, str], list[dict]] = generate_tokens,
    capacity_runner=run_capacity_k6,
    stage_context_factory=None,
    stage_context_cleanup=None,
    stage_validator=None,
) -> tuple[int, Path]:
    highest_rate = max(options.rates)
    preallocated = options.pre_allocated_vus or default_preallocated_vus(
        highest_rate
    )
    maximum = options.max_vus or default_max_vus(highest_rate, preallocated)
    tokens = token_provider(maximum, password)

    runtime = Path(tempfile.mkdtemp(prefix="la_bid_capacity_"))
    token_file = runtime / "tokens.json"
    token_file.write_text(
        json.dumps(tokens, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    create_stage = stage_context_factory or (
        lambda target_rps: create_bid_stage(password, target_rps)
    )
    cleanup_stage = stage_context_cleanup or cleanup_bid_stage
    validate_stage = stage_validator or validate_bid_stage

    try:
        return capacity_runner(
            scenario=scenario,
            auction_id=None,
            room_id=None,
            base_url=base_url,
            k6_bin=k6_bin,
            options=options,
            health_check=health_check,
            metric_prefix="bid",
            assessor=assess_bid_stage,
            extra_env={
                "TOKENS_FILE": str(token_file),
                "START_PRICE": str(BID_START_PRICE),
                "INCREMENT_AMOUNT": str(BID_INCREMENT_AMOUNT),
                "MAX_PRICE": str(BID_MAX_PRICE),
            },
            stage_context_factory=create_stage,
            stage_context_cleanup=cleanup_stage,
            stage_validator=validate_stage,
        )
    finally:
        if keep_artifacts:
            info_log(f"出价容量临时文件保留: {runtime}")
        else:
            shutil.rmtree(runtime, ignore_errors=True)
