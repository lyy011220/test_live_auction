"""k6 性能场景注册表: 单一事实源, 映射 场景名 -> 脚本/VU数/case_id/预期终价。

runner.py 与 summarize.py 共用此表, tests/perf 也按 case_id 反查。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

K6_DIR = Path(__file__).resolve().parent / "k6"


@dataclass(frozen=True)
class Scenario:
    name: str
    script: Path
    vus: int
    case_id: str
    # 预期终价: None 表示由 k6 脚本内推导 (如 bid_concurrent 用 max(出价集合)),
    # 不在此重复声明, 避免改脚本后 registry 过时。非 None 仅作显式断言用。
    expected_final_price: float | None
    max_duration: str
    description: str


SCENARIOS: dict[str, Scenario] = {
    "bid_concurrent": Scenario(
        name="bid_concurrent",
        script=K6_DIR / "bid_concurrent.js",
        vus=20,
        case_id="PERF-LOAD-001",
        expected_final_price=None,  # k6 脚本内 Math.max(ROUND_AMOUNTS) 推导
        max_duration="1m",
        description="20 VU 乱序不同金额并发, 最终唯一最高价由集合 max 决定",
    ),
    "bid_same_amount_race": Scenario(
        name="bid_same_amount_race",
        script=K6_DIR / "bid_same_amount_race.js",
        vus=5,
        case_id="PERF-LOAD-002",
        expected_final_price=None,  # 等于 k6 脚本内 BID_AMOUNT
        max_duration="30s",
        description="5 VU 同价竞争, 恰一人成为有效最高出价",
    ),
    "bid_repeat_rounds": Scenario(
        name="bid_repeat_rounds",
        script=K6_DIR / "bid_repeat_rounds.js",
        vus=5,
        case_id="PERF-LOAD-003",
        expected_final_price=None,
        max_duration="2m",
        description="5 VU × 3 轮递增出价, 校验无 5xx 且终态一致 (轮间无污染)",
    ),
    "ws_bid_concurrent": Scenario(
        name="ws_bid_concurrent",
        script=K6_DIR / "ws_bid_concurrent.js",
        vus=20,
        case_id="PERF-LOAD-004",
        expected_final_price=None,  # 由 k6 脚本内 AMOUNTS 集合 max 推导
        max_duration="1m",
        description="20 VU 经 STOMP-over-WebSocket 并发出价, 校验 BID 广播往返时延与最终价一致",
    ),
    "mixed_stress": Scenario(
        name="mixed_stress",
        script=K6_DIR / "mixed_stress.js",
        vus=50,
        case_id="PERF-STRESS-001",
        expected_final_price=None,
        max_duration="5m30s",
        description="50 VU 混合场景 (首轮流式出价 + 持续读详情/排行榜) 压测 5 分钟, 校验无 5xx 崩溃且错误率 < 1%",
    ),
}


def get_scenario(name: str) -> Scenario:
    if name not in SCENARIOS:
        raise KeyError(f"未知场景: {name}, 可选: {sorted(SCENARIOS)}")
    return SCENARIOS[name]


def scenario_by_case_id(case_id: str) -> Scenario | None:
    for s in SCENARIOS.values():
        if s.case_id == case_id:
            return s
    return None
