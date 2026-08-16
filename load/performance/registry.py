from __future__ import annotations

from pathlib import Path

from load.shared.model import Scenario


K6_PERFORMANCE_DIR = Path(__file__).resolve().parents[1] / "k6" / "performance"

SCENARIOS: dict[str, Scenario] = {
    "mixed_stress": Scenario(
        name="mixed_stress",
        script=K6_PERFORMANCE_DIR / "mixed_stress.js",
        vus=50,
        case_id="PERF-STRESS-001",
        expected_final_price=None,
        max_duration="5m30s",
        description="50 VU 混合场景持续压测 5 分钟",
        purpose="performance",
    ),
    "detail_capacity": Scenario(
        name="detail_capacity",
        script=K6_PERFORMANCE_DIR / "detail_capacity.js",
        vus=0,
        case_id="PERF-CAPACITY-001",
        expected_final_price=None,
        max_duration="10m",
        description="竞拍详情热点接口按 50/100/200/400 RPS 独立运行",
        purpose="performance",
        requires_tokens=False,
        target_rates=(50, 100, 200, 400),
        stage_duration="2m",
        cooldown_seconds=15,
        auction_duration_minutes=20,
    ),
    "bid_capacity": Scenario(
        name="bid_capacity",
        script=K6_PERFORMANCE_DIR / "bid_capacity.js",
        vus=0,
        case_id="PERF-CAPACITY-002",
        expected_final_price=None,
        max_duration="12m",
        description="单竞拍热点出价按 25/50/100/200/400 RPS 独立运行",
        purpose="performance",
        requires_tokens=True,
        target_rates=(25, 50, 100, 200, 400),
        stage_duration="2m",
        cooldown_seconds=20,
        auction_duration_minutes=20,
    ),
}


def get_scenario(name: str) -> Scenario:
    if name not in SCENARIOS:
        raise KeyError(f"未知性能场景: {name}，可选: {sorted(SCENARIOS)}")
    return SCENARIOS[name]


def scenario_by_case_id(case_id: str) -> Scenario | None:
    return next((s for s in SCENARIOS.values() if s.case_id == case_id), None)
