from __future__ import annotations

from pathlib import Path

from load.shared.model import Scenario


K6_CONCURRENCY_DIR = Path(__file__).resolve().parents[1] / "k6" / "concurrency"

SCENARIOS: dict[str, Scenario] = {
    "bid_concurrent": Scenario(
        name="bid_concurrent",
        script=K6_CONCURRENCY_DIR / "bid_concurrent.js",
        vus=20,
        case_id="PERF-LOAD-001",
        expected_final_price=None,
        max_duration="1m",
        description="20 VU 乱序不同金额并发，最终价格由唯一最高有效出价决定",
    ),
    "bid_same_amount_race": Scenario(
        name="bid_same_amount_race",
        script=K6_CONCURRENCY_DIR / "bid_same_amount_race.js",
        vus=5,
        case_id="PERF-LOAD-002",
        expected_final_price=None,
        max_duration="30s",
        description="5 VU 同价竞争，恰一人成为有效最高出价",
    ),
    "bid_repeat_rounds": Scenario(
        name="bid_repeat_rounds",
        script=K6_CONCURRENCY_DIR / "bid_repeat_rounds.js",
        vus=5,
        case_id="PERF-LOAD-003",
        expected_final_price=None,
        max_duration="2m",
        description="5 VU 乘 3 轮递增出价，校验最终投影一致性",
    ),
    "ws_bid_concurrent": Scenario(
        name="ws_bid_concurrent",
        script=K6_CONCURRENCY_DIR / "ws_bid_concurrent.js",
        vus=20,
        case_id="PERF-LOAD-004",
        expected_final_price=None,
        max_duration="1m",
        description="20 VU 经 STOMP-over-WebSocket 并发出价并校验广播",
    ),
}


def get_scenario(name: str) -> Scenario:
    if name not in SCENARIOS:
        raise KeyError(f"未知并发场景: {name}，可选: {sorted(SCENARIOS)}")
    return SCENARIOS[name]


def scenario_by_case_id(case_id: str) -> Scenario | None:
    return next((s for s in SCENARIOS.values() if s.case_id == case_id), None)

