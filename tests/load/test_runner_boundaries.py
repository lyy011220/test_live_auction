import subprocess
import sys
from pathlib import Path

from load.performance import runner as performance_runner


ROOT = Path(__file__).resolve().parents[2]


def _run_help(module: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", module, "--help"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def test_concurrency_runner_exposes_only_correctness_scenarios():
    result = _run_help("load.concurrency.runner")

    assert result.returncode == 0, result.stderr
    assert "bid_concurrent" in result.stdout
    assert "ws_bid_concurrent" in result.stdout
    assert "detail_capacity" not in result.stdout
    assert "mixed_stress" not in result.stdout


def test_performance_runner_exposes_only_load_scenarios():
    result = _run_help("load.performance.runner")

    assert result.returncode == 0, result.stderr
    assert "detail_capacity" in result.stdout
    assert "mixed_stress" in result.stdout
    assert "bid_concurrent" not in result.stdout
    assert "ws_bid_concurrent" not in result.stdout


def test_legacy_runner_module_is_removed():
    result = _run_help("load.runner")

    assert result.returncode != 0
    assert "No module named load.runner" in result.stderr


def test_performance_runner_routes_bid_capacity_without_shared_prepare(
    monkeypatch,
    tmp_path,
):
    captured = {}

    def fail_prepare(*_args, **_kwargs):
        raise AssertionError("bid capacity must prepare one auction per stage")

    def fake_run_bid_capacity(**kwargs):
        captured.update(kwargs)
        return 0, tmp_path / "run"

    monkeypatch.setattr(performance_runner, "prepare", fail_prepare)
    monkeypatch.setitem(
        performance_runner.CAPACITY_EXECUTORS,
        "bid_capacity",
        fake_run_bid_capacity,
    )
    monkeypatch.setattr(
        performance_runner,
        "read_config_yaml",
        lambda section, key=None: {
            ("BASE", "base_live_auction_url"): "http://localhost:8080",
            ("BASE", "ws_url"): "ws://localhost:8080/ws/websocket",
            ("STOMP", "bid_destination"): "/app/bid",
            ("K6", "bin"): "k6",
        }.get((section, key)),
    )
    monkeypatch.setattr(performance_runner, "default_password", lambda: "secret")

    result = performance_runner.main([
        "--scenario",
        "bid_capacity",
        "--rates",
        "25",
        "--duration",
        "1s",
        "--cooldown",
        "0",
        "--pre-allocated-vus",
        "1",
        "--max-vus",
        "2",
        "--reports-root",
        str(tmp_path),
    ])

    assert result == 0
    assert captured["scenario"].name == "bid_capacity"
    assert captured["password"] == "secret"
    assert captured["options"].rates == (25,)
    assert captured["options"].reports_root == tmp_path


def test_capacity_executor_registry_contains_both_capacity_scenarios():
    assert set(performance_runner.CAPACITY_EXECUTORS) == {
        "detail_capacity",
        "bid_capacity",
    }
