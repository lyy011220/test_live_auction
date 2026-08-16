"""固定 RPS 容量场景的命令构造、分档编排与结果判定。"""
from __future__ import annotations

import argparse
import json
import math
import subprocess
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from commons.logger_util import info_log
from load.provenance import backend_identity
from load.summarize import parse, write_capacity_markdown

ROOT = Path(__file__).resolve().parents[2]
CAPACITY_REPORTS_ROOT = ROOT / "reports" / "k6" / "detail_capacity"


@dataclass(frozen=True)
class CapacityOptions:
    rates: tuple[int, ...]
    duration: str
    cooldown_seconds: int
    reports_root: Path
    pre_allocated_vus: int | None = None
    max_vus: int | None = None


def default_preallocated_vus(target_rps: int) -> int:
    return max(50, math.ceil(target_rps * 0.25))


def default_max_vus(target_rps: int, preallocated: int) -> int:
    return max(preallocated, target_rps * 2)


def parse_capacity_rates(value: str) -> tuple[int, ...]:
    try:
        rates = tuple(int(part.strip()) for part in value.split(","))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "rates must be comma-separated positive integers"
        ) from exc
    if not rates or any(rate <= 0 for rate in rates):
        raise argparse.ArgumentTypeError(
            "rates must be comma-separated positive integers"
        )
    if len(set(rates)) != len(rates):
        raise argparse.ArgumentTypeError("rates must not contain duplicates")
    return rates


def capacity_duration_seconds(value: str) -> float:
    units = {"s": 1, "m": 60, "h": 3600}
    if len(value) < 2 or value[-1] not in units:
        raise ValueError("capacity duration must end with s, m, or h")
    try:
        seconds = float(value[:-1]) * units[value[-1]]
    except ValueError as exc:
        raise ValueError("capacity duration must be a positive number") from exc
    if seconds <= 0:
        raise ValueError("capacity duration must be positive")
    return seconds


def build_capacity_command(
    *,
    scenario,
    auction_id,
    base_url: str,
    k6_bin: str,
    target_rps: int,
    duration: str,
    summary_path: Path,
    pre_allocated_vus: int | None,
    max_vus: int | None,
    extra_env: dict[str, str] | None = None,
) -> list[str]:
    """构造单个固定 RPS 档位的独立 k6 命令。"""
    preallocated = (
        pre_allocated_vus
        if pre_allocated_vus is not None
        else default_preallocated_vus(target_rps)
    )
    maximum = (
        max_vus
        if max_vus is not None
        else default_max_vus(target_rps, preallocated)
    )
    if preallocated <= 0:
        raise ValueError("pre_allocated_vus must be positive")
    if maximum < preallocated:
        raise ValueError("max_vus must be >= pre_allocated_vus")

    command = [
        k6_bin,
        "run",
        "-e",
        f"BASE_URL={base_url.rstrip('/')}",
        "-e",
        f"TARGET_RPS={target_rps}",
        "-e",
        f"DURATION={duration}",
        "-e",
        f"PRE_ALLOCATED_VUS={preallocated}",
        "-e",
        f"MAX_VUS={maximum}",
    ]
    if auction_id is not None:
        command.extend(["-e", f"ITEM_ID={auction_id}"])
    for name, value in sorted((extra_env or {}).items()):
        command.extend(["-e", f"{name}={value}"])
    command.extend([
        "--summary-export",
        str(summary_path),
        str(scenario.script),
    ])
    return command


def run_capacity_k6(
    *,
    scenario,
    auction_id,
    room_id,
    base_url: str,
    k6_bin: str,
    options: CapacityOptions,
    assessor: Callable[..., tuple[str, list[str]]],
    process_runner=subprocess.run,
    sleep_fn=time.sleep,
    identity_provider=backend_identity,
    health_check=None,
    metric_prefix: str = "detail",
    extra_env: Mapping[str, str] | None = None,
    stage_context_factory: Callable[[int], Mapping] | None = None,
    stage_context_cleanup: Callable[[Mapping], None] | None = None,
    stage_validator: Callable[[Mapping, dict], list[str]] | None = None,
) -> tuple[int, Path]:
    """按固定 RPS 档位编排容量测试。"""
    if not options.rates or any(rate <= 0 for rate in options.rates):
        raise ValueError("capacity rates must be positive")
    if options.cooldown_seconds < 0:
        raise ValueError("cooldown_seconds must not be negative")
    duration_seconds = capacity_duration_seconds(options.duration)

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    run_dir = options.reports_root / run_id
    run_dir.mkdir(parents=True, exist_ok=False)

    identity = identity_provider(base_url)
    manifest = {
        "schema_version": 1,
        "run_id": run_id,
        "scenario": scenario.name,
        "case_id": scenario.case_id,
        "base_url": base_url.rstrip("/"),
        "auction_id": auction_id,
        "room_id": room_id,
        "rates": list(options.rates),
        "duration": options.duration,
        "cooldown_seconds": options.cooldown_seconds,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "completed_at": None,
        "backend": identity,
        "stages": [],
        "not_run_rates": [],
    }

    manifest_path = run_dir / "manifest.json"

    def persist() -> None:
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        write_capacity_markdown(run_dir, manifest)

    persist()
    baseline_p95 = None
    overall_exit_code = 0

    for index, target_rps in enumerate(options.rates):
        if health_check is not None:
            try:
                healthy_before_stage = bool(health_check())
            except Exception as exc:  # noqa: BLE001
                healthy_before_stage = False
                info_log(f"容量档位前健康检查异常: {exc}")
            if not healthy_before_stage:
                manifest["stop_reason"] = "health_check_before_stage"
                manifest["not_run_rates"] = list(options.rates[index:])
                overall_exit_code = 1
                persist()
                break

        stage_context = (
            dict(stage_context_factory(target_rps))
            if stage_context_factory is not None
            else {"auction_id": auction_id, "room_id": room_id}
        )
        stage_auction_id = stage_context.get("auction_id", auction_id)
        stage_room_id = stage_context.get("room_id", room_id)
        stage_env = dict(extra_env or {})
        stage_env.update(stage_context.get("extra_env") or {})
        stage_cleaned = False

        def cleanup_current_stage() -> bool:
            nonlocal stage_cleaned
            if stage_cleaned or stage_context_cleanup is None:
                return True
            stage_cleaned = True
            try:
                stage_context_cleanup(stage_context)
                return True
            except Exception as exc:  # noqa: BLE001
                info_log(f"容量档位资源清理失败: {exc}")
                return False

        stem = f"{scenario.name}_{target_rps:04d}rps"
        summary_path = run_dir / f"{stem}.json"
        metadata_path = run_dir / f"{stem}.meta.json"
        stdout_path = run_dir / f"{stem}.stdout.log"
        stderr_path = run_dir / f"{stem}.stderr.log"
        try:
            command = build_capacity_command(
                scenario=scenario,
                auction_id=stage_auction_id,
                base_url=base_url,
                k6_bin=k6_bin,
                target_rps=target_rps,
                duration=options.duration,
                summary_path=summary_path,
                pre_allocated_vus=options.pre_allocated_vus,
                max_vus=options.max_vus,
                extra_env=stage_env,
            )
        except BaseException:
            cleanup_current_stage()
            raise
        started_at = datetime.now(timezone.utc).isoformat()
        info_log(f"容量档位 {target_rps} RPS: {' '.join(command)}")

        try:
            result = process_runner(
                command,
                cwd=str(ROOT),
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            exit_code = result.returncode
            stdout = result.stdout or ""
            stderr = result.stderr or ""
        except OSError as exc:
            exit_code = 127
            stdout = ""
            stderr = str(exc)
        except BaseException:
            cleanup_current_stage()
            raise

        try:
            stdout_path.write_text(stdout, encoding="utf-8")
            stderr_path.write_text(stderr, encoding="utf-8")
        except BaseException:
            cleanup_current_stage()
            raise
        completed_at = datetime.now(timezone.utc).isoformat()

        metrics = None
        assessment = "STOP"
        reasons = []
        try:
            if summary_path.exists():
                parsed = parse(summary_path)
                endpoint = (parsed.get("performance_endpoints") or {}).get(
                    metric_prefix
                )
                if endpoint:
                    metrics = dict(endpoint)
                    if isinstance(metrics.get("request_count"), (int, float)):
                        metrics["actual_rps"] = (
                            metrics["request_count"] / duration_seconds
                        )
                    metrics["dropped_iterations"] = parsed.get(
                        "dropped_iterations", 0
                    )
                    metrics["vus_max"] = parsed.get("vus_max")
                    assessment, reasons = assessor(
                        metrics=metrics,
                        target_rps=target_rps,
                        baseline_p95=baseline_p95,
                        k6_exit_code=exit_code,
                    )
                    if baseline_p95 is None and isinstance(
                        metrics.get(
                            "handled_duration_p95",
                            metrics.get("success_duration_p95"),
                        ),
                        (int, float),
                    ):
                        baseline_p95 = metrics.get(
                            "handled_duration_p95",
                            metrics.get("success_duration_p95"),
                        )
                else:
                    reasons = [f"missing_{metric_prefix}_metrics"]
            else:
                reasons = ["missing_summary"]
        except BaseException:
            cleanup_current_stage()
            raise

        if health_check is not None:
            try:
                healthy_after_stage = bool(health_check())
            except Exception as exc:  # noqa: BLE001
                healthy_after_stage = False
                info_log(f"容量档位后健康检查异常: {exc}")
            if not healthy_after_stage:
                assessment = "STOP"
                reasons.append("health_check_after_stage")

        if stage_validator is not None and metrics is not None:
            try:
                validation_reasons = stage_validator(stage_context, metrics)
            except BaseException:
                cleanup_current_stage()
                raise
            if validation_reasons:
                assessment = "STOP"
                reasons.extend(
                    reason
                    for reason in validation_reasons
                    if reason not in reasons
                )

        if not cleanup_current_stage():
            assessment = "STOP"
            reasons.append("stage_cleanup_failed")

        if exit_code != 0 and overall_exit_code == 0:
            overall_exit_code = exit_code
        if assessment == "KNEE" and overall_exit_code == 0:
            overall_exit_code = 1
        if assessment == "STOP" and overall_exit_code == 0:
            overall_exit_code = exit_code or 1

        stage = {
            "target_rps": target_rps,
            "auction_id": stage_auction_id,
            "room_id": stage_room_id,
            "started_at": started_at,
            "completed_at": completed_at,
            "k6_exit_code": exit_code,
            "assessment": assessment,
            "reasons": reasons,
            "metrics": metrics,
            "summary_file": summary_path.name if summary_path.exists() else None,
            "metadata_file": metadata_path.name,
            "stdout_file": stdout_path.name,
            "stderr_file": stderr_path.name,
        }
        manifest["stages"].append(stage)

        metadata_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "scenario": scenario.name,
                    "case_id": scenario.case_id,
                    "target_rps": target_rps,
                    "duration": options.duration,
                    "base_url": base_url.rstrip("/"),
                    "auction_id": stage_auction_id,
                    "room_id": stage_room_id,
                    "started_at": started_at,
                    "completed_at": completed_at,
                    "k6_exit_code": exit_code,
                    "assessment": assessment,
                    "backend": identity,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        if assessment == "STOP":
            manifest["not_run_rates"] = list(options.rates[index + 1:])
            persist()
            break

        persist()
        if index < len(options.rates) - 1:
            sleep_fn(options.cooldown_seconds)

    manifest["overall_exit_code"] = overall_exit_code
    manifest["completed_at"] = datetime.now(timezone.utc).isoformat()
    persist()
    info_log(f"容量测试报告: {run_dir}")
    return overall_exit_code, run_dir
