import argparse
import json
import subprocess
from pathlib import Path

import pytest

from load.performance.capacity import (
    CapacityOptions,
    build_capacity_command,
    parse_capacity_rates,
    run_capacity_k6,
)
from load.performance.registry import get_scenario
from load.performance.scenarios.bid_hotspot_capacity import assess_bid_stage
from load.performance.scenarios.detail_capacity import assess_detail_stage


def _summary(target_rps: int, technical_failure_rate: float = 0) -> dict:
    return {
        "root_group": {"name": ""},
        "state": {"isFailed": technical_failure_rate >= 0.10},
        "metrics": {
            "checks": {"value": 1, "passes": 1, "fails": 0},
            "detail_requests": {
                "count": target_rps * 120,
                "rate": float(target_rps),
            },
            "detail_success_rate": {
                "value": 1 - technical_failure_rate,
            },
            "detail_technical_failure_rate": {
                "value": technical_failure_rate,
            },
            "detail_4xx": {"count": 0},
            "detail_5xx": {
                "count": int(target_rps * 120 * technical_failure_rate),
            },
            "detail_network_errors": {"count": 0},
            "detail_success_duration": {
                "p(95)": 100 + target_rps / 10,
                "p(99)": 150 + target_rps / 10,
            },
            "dropped_iterations": {"count": 0},
            "vus": {"max": target_rps},
        },
    }


def _bid_summary(target_rps: int) -> dict:
    total = target_rps * 120
    return {
        "root_group": {"name": ""},
        "state": {"isFailed": False},
        "metrics": {
            "checks": {"value": 1, "passes": total, "fails": 0},
            "bid_requests": {"count": total, "rate": float(target_rps)},
            "bid_success_rate": {"value": 0.25},
            "bid_technical_failure_rate": {"value": 0},
            "bid_4xx": {"count": int(total * 0.75)},
            "bid_5xx": {"count": 0},
            "bid_network_errors": {"count": 0},
            "bid_success_duration": {"p(95)": 100, "p(99)": 150},
            "bid_accepted": {"count": int(total * 0.25)},
            "bid_business_rejections": {"count": int(total * 0.75)},
            "bid_unexpected_rejections": {"count": 0},
            "bid_handled_rate": {"value": 1},
            "bid_handled_duration": {"p(95)": 110, "p(99)": 160},
            "bid_accepted_amount": {"max": 10000},
            "dropped_iterations": {"count": 0},
            "vus": {"max": target_rps},
        },
    }


def _target_from_command(command: list[str]) -> int:
    value = next(part for part in command if part.startswith("TARGET_RPS="))
    return int(value.split("=", 1)[1])


def _summary_path_from_command(command: list[str]) -> Path:
    index = command.index("--summary-export")
    return Path(command[index + 1])


@pytest.mark.parametrize("value", ["", "0", "25,25", "abc"])
def test_parse_capacity_rates_rejects_invalid_values(value):
    with pytest.raises(argparse.ArgumentTypeError):
        parse_capacity_rates(value)


def test_build_capacity_command_contains_one_fixed_rate(tmp_path):
    scenario = get_scenario("detail_capacity")
    options = CapacityOptions(
        rates=(50, 100, 200, 400),
        duration="2m",
        cooldown_seconds=15,
        reports_root=tmp_path,
    )

    command = build_capacity_command(
        scenario=scenario,
        auction_id=77,
        base_url="http://localhost:8080",
        k6_bin="k6",
        target_rps=100,
        duration=options.duration,
        summary_path=tmp_path / "100.json",
        pre_allocated_vus=options.pre_allocated_vus,
        max_vus=options.max_vus,
    )
    joined = " ".join(str(part) for part in command)

    assert "TARGET_RPS=100" in joined
    assert "ITEM_ID=77" in joined
    assert "DURATION=2m" in joined
    assert "PRE_ALLOCATED_VUS=50" in joined
    assert "MAX_VUS=200" in joined
    assert "TOKENS_FILE" not in joined


def test_build_capacity_command_appends_bid_environment(tmp_path):
    scenario = get_scenario("detail_capacity")

    command = build_capacity_command(
        scenario=scenario,
        auction_id=77,
        base_url="http://localhost:8080",
        k6_bin="k6",
        target_rps=25,
        duration="2m",
        summary_path=tmp_path / "25.json",
        pre_allocated_vus=20,
        max_vus=50,
        extra_env={
            "TOKENS_FILE": str(tmp_path / "tokens.json"),
            "START_PRICE": "100",
            "INCREMENT_AMOUNT": "1",
            "MAX_PRICE": "100000",
        },
    )

    assert f"TOKENS_FILE={tmp_path / 'tokens.json'}" in command
    assert "START_PRICE=100" in command
    assert "INCREMENT_AMOUNT=1" in command
    assert "MAX_PRICE=100000" in command


def test_build_capacity_command_allows_scenario_owned_resource_environment(
    tmp_path,
):
    command = build_capacity_command(
        scenario=get_scenario("detail_capacity"),
        auction_id=None,
        base_url="http://localhost:8080",
        k6_bin="k6",
        target_rps=25,
        duration="2m",
        summary_path=tmp_path / "25.json",
        pre_allocated_vus=10,
        max_vus=20,
        extra_env={"ITEM_IDS": "101,102,103"},
    )

    assert "ITEM_ID=None" not in command
    assert "ITEM_IDS=101,102,103" in command


def test_bid_capacity_accepts_expected_business_rejections():
    assessment, reasons = assess_bid_stage(
        metrics={
            "actual_rps": 100.0,
            "technical_failure_rate": 0.0,
            "handled_rate": 1.0,
            "unexpected_rejections": 0,
            "handled_duration_p95": 120.0,
            "dropped_iterations": 0,
        },
        target_rps=100,
        baseline_p95=100.0,
        k6_exit_code=0,
    )

    assert assessment == "PASS"
    assert reasons == []


def test_bid_capacity_stops_on_unexpected_rejection():
    assessment, reasons = assess_bid_stage(
        metrics={
            "actual_rps": 100.0,
            "technical_failure_rate": 0.0,
            "handled_rate": 0.99,
            "unexpected_rejections": 1,
            "handled_duration_p95": 120.0,
            "dropped_iterations": 0,
        },
        target_rps=100,
        baseline_p95=100.0,
        k6_exit_code=0,
    )

    assert assessment == "STOP"
    assert reasons == ["unexpected_rejections_detected"]


def test_bid_capacity_reports_unexpected_rejection_and_dropped_iterations():
    assessment, reasons = assess_bid_stage(
        metrics={
            "actual_rps": 100.0,
            "technical_failure_rate": 0.0,
            "handled_rate": 0.99,
            "unexpected_rejections": 1,
            "handled_duration_p95": 120.0,
            "dropped_iterations": 1,
        },
        target_rps=100,
        baseline_p95=100.0,
        k6_exit_code=99,
    )

    assert assessment == "STOP"
    assert reasons == [
        "unexpected_rejections_detected",
        "dropped_iterations",
        "k6_exit_code_99",
    ]


def test_run_capacity_decodes_k6_output_as_utf8(tmp_path):
    def fake_process(command, **kwargs):
        summary_path = _summary_path_from_command(command)
        summary_path.write_text(
            json.dumps(_summary(1)),
            encoding="utf-8",
        )
        stdout = "k6 progress ✓".encode("utf-8").decode(
            kwargs.get("encoding") or "gbk",
            errors=kwargs.get("errors") or "strict",
        )
        return subprocess.CompletedProcess(command, 0, stdout, "")

    exit_code, run_dir = run_capacity_k6(
        scenario=get_scenario("detail_capacity"),
        auction_id=77,
        room_id=88,
        base_url="http://localhost:8080",
        k6_bin="k6",
        options=CapacityOptions(
            rates=(1,),
            duration="1s",
            cooldown_seconds=0,
            reports_root=tmp_path,
        ),
        process_runner=fake_process,
        identity_provider=lambda _base_url: {"openapi_sha256": "abc"},
        health_check=lambda: True,
        assessor=assess_detail_stage,
    )

    assert exit_code == 0
    assert (
        run_dir / "detail_capacity_0001rps.stdout.log"
    ).read_text(encoding="utf-8") == "k6 progress ✓"


def test_run_capacity_calculates_rps_from_scenario_duration(tmp_path):
    def fake_process(command, **_kwargs):
        summary = _summary(50, technical_failure_rate=1 / 6001)
        summary["metrics"]["detail_requests"] = {
            "count": 6001,
            "rate": 48.7573756661774,
        }
        summary["metrics"]["detail_network_errors"] = {"count": 1}
        summary_path = _summary_path_from_command(command)
        summary_path.write_text(json.dumps(summary), encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, "", "")

    exit_code, run_dir = run_capacity_k6(
        scenario=get_scenario("detail_capacity"),
        auction_id=77,
        room_id=88,
        base_url="http://localhost:8080",
        k6_bin="k6",
        options=CapacityOptions(
            rates=(50,),
            duration="2m",
            cooldown_seconds=0,
            reports_root=tmp_path,
        ),
        process_runner=fake_process,
        identity_provider=lambda _base_url: {"openapi_sha256": "abc"},
        health_check=lambda: True,
        assessor=assess_detail_stage,
    )

    manifest = json.loads(
        (run_dir / "manifest.json").read_text(encoding="utf-8")
    )
    stage = manifest["stages"][0]
    assert exit_code == 0
    assert stage["assessment"] == "PASS"
    assert stage["metrics"]["actual_rps"] == 50.00833333333333


def test_run_capacity_uses_four_independent_processes(tmp_path):
    commands = []
    cooldowns = []
    health_checks = []

    def fake_process(command, **_kwargs):
        commands.append(command)
        target_rps = _target_from_command(command)
        summary_path = _summary_path_from_command(command)
        summary_path.write_text(
            json.dumps(_summary(target_rps)),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0, "stdout", "")

    options = CapacityOptions(
        rates=(50, 100, 200, 400),
        duration="2m",
        cooldown_seconds=15,
        reports_root=tmp_path,
    )

    def healthy():
        health_checks.append(True)
        return True

    exit_code, run_dir = run_capacity_k6(
        scenario=get_scenario("detail_capacity"),
        auction_id=77,
        room_id=88,
        base_url="http://localhost:8080",
        k6_bin="k6",
        options=options,
        process_runner=fake_process,
        sleep_fn=cooldowns.append,
        identity_provider=lambda _base_url: {"openapi_sha256": "abc"},
        health_check=healthy,
        assessor=assess_detail_stage,
    )

    assert exit_code == 0
    assert [_target_from_command(command) for command in commands] == [
        50,
        100,
        200,
        400,
    ]
    assert cooldowns == [15, 15, 15]
    assert len(health_checks) == 8
    assert len({_summary_path_from_command(command) for command in commands}) == 4
    assert all("ITEM_ID=77" in command for command in commands)
    assert (run_dir / "manifest.json").exists()
    assert (run_dir / "summary.md").exists()

    manifest = json.loads(
        (run_dir / "manifest.json").read_text(encoding="utf-8")
    )
    assert [stage["target_rps"] for stage in manifest["stages"]] == [
        50,
        100,
        200,
        400,
    ]
    assert all(stage["assessment"] == "PASS" for stage in manifest["stages"])


def test_run_capacity_stops_at_ten_percent_technical_failures(tmp_path):
    commands = []
    cooldowns = []

    def fake_process(command, **_kwargs):
        commands.append(command)
        target_rps = _target_from_command(command)
        technical_failure_rate = {
            100: 0.02,
            200: 0.10,
        }.get(target_rps, 0)
        summary_path = _summary_path_from_command(command)
        summary_path.write_text(
            json.dumps(_summary(target_rps, technical_failure_rate)),
            encoding="utf-8",
        )
        exit_code = 99 if technical_failure_rate >= 0.01 else 0
        return subprocess.CompletedProcess(command, exit_code, "", "")

    options = CapacityOptions(
        rates=(50, 100, 200, 400),
        duration="2m",
        cooldown_seconds=15,
        reports_root=tmp_path,
    )

    exit_code, run_dir = run_capacity_k6(
        scenario=get_scenario("detail_capacity"),
        auction_id=77,
        room_id=88,
        base_url="http://localhost:8080",
        k6_bin="k6",
        options=options,
        process_runner=fake_process,
        sleep_fn=cooldowns.append,
        identity_provider=lambda _base_url: {"openapi_sha256": "abc"},
        assessor=assess_detail_stage,
    )

    assert exit_code == 99
    assert [_target_from_command(command) for command in commands] == [
        50,
        100,
        200,
    ]
    assert cooldowns == [15, 15]

    manifest = json.loads(
        (run_dir / "manifest.json").read_text(encoding="utf-8")
    )
    assert [stage["assessment"] for stage in manifest["stages"]] == [
        "PASS",
        "KNEE",
        "STOP",
    ]
    assert manifest["not_run_rates"] == [400]


def test_bid_capacity_uses_fresh_auction_for_every_rate(tmp_path):
    commands = []
    cleaned = []

    def fake_process(command, **_kwargs):
        commands.append(command)
        target_rps = _target_from_command(command)
        _summary_path_from_command(command).write_text(
            json.dumps(_bid_summary(target_rps)),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0, "", "")

    contexts = {
        25: {"auction_id": 101, "room_id": 201},
        50: {"auction_id": 102, "room_id": 202},
    }

    exit_code, run_dir = run_capacity_k6(
        scenario=get_scenario("detail_capacity"),
        auction_id=None,
        room_id=None,
        base_url="http://localhost:8080",
        k6_bin="k6",
        options=CapacityOptions(
            rates=(25, 50),
            duration="2m",
            cooldown_seconds=0,
            reports_root=tmp_path,
        ),
        process_runner=fake_process,
        sleep_fn=lambda _seconds: None,
        identity_provider=lambda _base_url: {"openapi_sha256": "abc"},
        metric_prefix="bid",
        assessor=assess_bid_stage,
        extra_env={"TOKENS_FILE": str(tmp_path / "tokens.json")},
        stage_context_factory=lambda rate: contexts[rate],
        stage_context_cleanup=lambda context: cleaned.append(
            context["auction_id"]
        ),
    )

    assert exit_code == 0
    assert [
        next(part for part in command if part.startswith("ITEM_ID="))
        for command in commands
    ] == ["ITEM_ID=101", "ITEM_ID=102"]
    assert all(
        f"TOKENS_FILE={tmp_path / 'tokens.json'}" in command
        for command in commands
    )
    assert cleaned == [101, 102]

    manifest = json.loads(
        (run_dir / "manifest.json").read_text(encoding="utf-8")
    )
    assert [stage["auction_id"] for stage in manifest["stages"]] == [
        101,
        102,
    ]
    assert all(stage["assessment"] == "PASS" for stage in manifest["stages"])


def test_bid_capacity_stops_when_stage_state_is_inconsistent(tmp_path):
    commands = []
    cleaned = []

    def fake_process(command, **_kwargs):
        commands.append(command)
        target_rps = _target_from_command(command)
        _summary_path_from_command(command).write_text(
            json.dumps(_bid_summary(target_rps)),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0, "", "")

    exit_code, run_dir = run_capacity_k6(
        scenario=get_scenario("detail_capacity"),
        auction_id=None,
        room_id=None,
        base_url="http://localhost:8080",
        k6_bin="k6",
        options=CapacityOptions(
            rates=(25, 50),
            duration="2m",
            cooldown_seconds=0,
            reports_root=tmp_path,
        ),
        process_runner=fake_process,
        identity_provider=lambda _base_url: {"openapi_sha256": "abc"},
        metric_prefix="bid",
        assessor=assess_bid_stage,
        stage_context_factory=lambda rate: {
            "auction_id": 100 + rate,
            "room_id": 200 + rate,
        },
        stage_context_cleanup=lambda context: cleaned.append(
            context["auction_id"]
        ),
        stage_validator=lambda _context, _metrics: ["bid_count_mismatch"],
    )

    assert exit_code == 1
    assert len(commands) == 1
    assert cleaned == [125]

    manifest = json.loads(
        (run_dir / "manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["stages"][0]["assessment"] == "STOP"
    assert manifest["stages"][0]["reasons"] == ["bid_count_mismatch"]
    assert manifest["not_run_rates"] == [50]


def test_stage_cleanup_runs_when_summary_parsing_raises(tmp_path):
    cleaned = []

    def fake_process(command, **_kwargs):
        _summary_path_from_command(command).write_text("{", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, "", "")

    with pytest.raises(json.JSONDecodeError):
        run_capacity_k6(
            scenario=get_scenario("detail_capacity"),
            auction_id=None,
            room_id=None,
            base_url="http://localhost:8080",
            k6_bin="k6",
            options=CapacityOptions(
                rates=(25,),
                duration="2m",
                cooldown_seconds=0,
                reports_root=tmp_path,
            ),
            assessor=assess_bid_stage,
            process_runner=fake_process,
            identity_provider=lambda _base_url: {"openapi_sha256": "abc"},
            metric_prefix="bid",
            stage_context_factory=lambda _rate: {
                "auction_id": 125,
                "room_id": 225,
            },
            stage_context_cleanup=lambda context: cleaned.append(
                context["auction_id"]
            ),
        )

    assert cleaned == [125]


def test_stage_cleanup_runs_when_command_construction_raises(tmp_path):
    cleaned = []

    with pytest.raises(ValueError, match="max_vus"):
        run_capacity_k6(
            scenario=get_scenario("detail_capacity"),
            auction_id=None,
            room_id=None,
            base_url="http://localhost:8080",
            k6_bin="k6",
            options=CapacityOptions(
                rates=(25,),
                duration="2m",
                cooldown_seconds=0,
                reports_root=tmp_path,
                pre_allocated_vus=10,
                max_vus=5,
            ),
            assessor=assess_bid_stage,
            identity_provider=lambda _base_url: {"openapi_sha256": "abc"},
            metric_prefix="bid",
            stage_context_factory=lambda _rate: {
                "auction_id": 125,
                "room_id": 225,
            },
            stage_context_cleanup=lambda context: cleaned.append(
                context["auction_id"]
            ),
        )

    assert cleaned == [125]
