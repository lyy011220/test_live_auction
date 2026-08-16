import json
from pathlib import Path
from types import SimpleNamespace

from load.performance.capacity import CapacityOptions
from load.performance.registry import get_scenario
from load.performance.scenarios import bid_hotspot_capacity
from load.performance.scenarios.bid_hotspot_capacity import (
    run_bid_hotspot_capacity,
    validate_bid_stage,
    validate_bid_snapshot,
)


def test_bid_capacity_scenario_is_registered():
    scenario = get_scenario("bid_capacity")

    assert scenario.script.name == "bid_capacity.js"
    assert scenario.target_rates == (25, 50, 100, 200, 400)
    assert scenario.stage_duration == "2m"
    assert scenario.cooldown_seconds == 20


def test_validate_bid_snapshot_accepts_consistent_detail():
    reasons = validate_bid_snapshot(
        metrics={"accepted": 3, "accepted_amount_max": 130},
        detail={
            "status": 2,
            "bidCount": 3,
            "currentPrice": 130,
        },
    )

    assert reasons == []


def test_validate_bid_snapshot_reports_detail_mismatches():
    reasons = validate_bid_snapshot(
        metrics={"accepted": 3, "accepted_amount_max": 130},
        detail={
            "status": 2,
            "bidCount": 2,
            "currentPrice": 129,
        },
    )

    assert reasons == [
        "bid_count_mismatch",
        "current_price_mismatch",
    ]


def test_validate_bid_snapshot_requires_live_auction():
    reasons = validate_bid_snapshot(
        metrics={"accepted": 1, "accepted_amount_max": 101},
        detail={
            "status": 4,
            "bidCount": 1,
            "currentPrice": 101,
        },
    )

    assert reasons == ["auction_not_live"]


def test_validate_bid_stage_does_not_query_ranking(monkeypatch):
    class DetailOnlyClient:
        def __init__(self, _client):
            pass

        def public_detail(self, _auction_id):
            return SimpleNamespace(
                is_ok=True,
                http_status=200,
                code=200,
                message="success",
                data={"status": 2, "bidCount": 1, "currentPrice": 101},
            )

    monkeypatch.setattr(
        bid_hotspot_capacity,
        "AuctionClient",
        DetailOnlyClient,
    )

    reasons = validate_bid_stage(
        {"auction_id": 7, "resource": {"merchantClient": object()}},
        {"accepted": 1, "accepted_amount_max": 101},
    )

    assert reasons == []


def test_run_bid_capacity_prepares_tokens_and_injects_stage_hooks(tmp_path):
    captured = {}

    def fake_capacity_runner(**kwargs):
        captured.update(kwargs)
        token_path = kwargs["extra_env"]["TOKENS_FILE"]
        captured["tokens"] = json.loads(
            Path(token_path).read_text(encoding="utf-8")
        )
        return 0, tmp_path / "run"

    scenario = get_scenario("bid_capacity")
    stage_factory = lambda rate: {  # noqa: E731
        "auction_id": 100 + rate,
        "room_id": 200 + rate,
    }
    stage_cleanup = lambda _context: None  # noqa: E731
    stage_validator = lambda _context, _metrics: []  # noqa: E731

    result = run_bid_hotspot_capacity(
        scenario=scenario,
        password="secret",
        base_url="http://localhost:8080",
        k6_bin="k6",
        options=CapacityOptions(
            rates=(25,),
            duration="2m",
            cooldown_seconds=0,
            reports_root=tmp_path,
            pre_allocated_vus=1,
            max_vus=2,
        ),
        token_provider=lambda count, password: [
            {"userid": index, "token": f"token-{index}"}
            for index in range(1, count + 1)
        ],
        capacity_runner=fake_capacity_runner,
        stage_context_factory=stage_factory,
        stage_context_cleanup=stage_cleanup,
        stage_validator=stage_validator,
    )

    assert result == (0, tmp_path / "run")
    assert captured["tokens"] == [
        {"userid": 1, "token": "token-1"},
        {"userid": 2, "token": "token-2"},
    ]
    assert captured["metric_prefix"] == "bid"
    assert captured["stage_context_factory"] is stage_factory
    assert captured["stage_context_cleanup"] is stage_cleanup
    assert captured["stage_validator"] is stage_validator
    assert captured["extra_env"]["START_PRICE"] == "100"
    assert captured["extra_env"]["INCREMENT_AMOUNT"] == "1"
    assert captured["extra_env"]["MAX_PRICE"] == "1000000"
