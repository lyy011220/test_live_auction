from __future__ import annotations

import argparse
from pathlib import Path

from clients.auth_client import default_password
from clients.health_client import HealthClient
from commons.logger_util import info_log
from commons.yaml_util import read_config_yaml
from load.performance.capacity import (
    CAPACITY_REPORTS_ROOT,
    CapacityOptions,
    parse_capacity_rates,
)
from load.performance.registry import SCENARIOS, get_scenario
from load.performance.scenarios.bid_hotspot_capacity import (
    run_bid_hotspot_capacity,
)
from load.performance.scenarios.detail_capacity import run_detail_capacity
from load.shared.execution import cleanup, prepare, run_k6


CAPACITY_EXECUTORS = {
    "detail_capacity": run_detail_capacity,
    "bid_capacity": run_bid_hotspot_capacity,
}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="k6 性能与容量场景调度")
    parser.add_argument("--scenario", choices=sorted(SCENARIOS), required=True)
    parser.add_argument(
        "--k6",
        default=None,
        help="k6 可执行文件路径；默认读取 K6_BIN/config",
    )
    parser.add_argument(
        "--keep-artifacts",
        action="store_true",
        help="保留临时 tokens.json",
    )
    parser.add_argument(
        "--rates",
        type=parse_capacity_rates,
        default=None,
        help="容量档位，逗号分隔；默认读取性能场景注册表",
    )
    parser.add_argument(
        "--duration",
        default=None,
        help="容量场景单档时长；默认读取性能场景注册表",
    )
    parser.add_argument(
        "--cooldown",
        type=int,
        default=None,
        help="容量场景档位间冷却秒数",
    )
    parser.add_argument("--pre-allocated-vus", type=int, default=None)
    parser.add_argument("--max-vus", type=int, default=None)
    parser.add_argument("--reports-root", type=Path, default=None)
    args = parser.parse_args(argv)

    scenario = get_scenario(args.scenario)
    password = default_password()
    base_url = (
        read_config_yaml("BASE", "base_live_auction_url")
        or "http://localhost:8080"
    ).rstrip("/")
    ws_url = (
        read_config_yaml("BASE", "ws_url")
        or base_url.replace("http", "ws", 1) + "/ws/websocket"
    )
    bid_destination = (
        read_config_yaml("STOMP", "bid_destination") or "/app/bid"
    )
    k6_bin = args.k6 or read_config_yaml("K6", "bin") or "k6"

    if scenario.target_rates:
        health_client = HealthClient()
        options = CapacityOptions(
            rates=args.rates or scenario.target_rates,
            duration=args.duration or scenario.stage_duration or "2m",
            cooldown_seconds=(
                args.cooldown
                if args.cooldown is not None
                else scenario.cooldown_seconds
            ),
            reports_root=(
                args.reports_root
                or CAPACITY_REPORTS_ROOT.parent / scenario.name
            ),
            pre_allocated_vus=args.pre_allocated_vus,
            max_vus=args.max_vus,
        )
        executor = CAPACITY_EXECUTORS[scenario.name]
        exit_code, _run_dir = executor(
            scenario=scenario,
            password=password,
            base_url=base_url,
            k6_bin=k6_bin,
            options=options,
            health_check=lambda: health_client.health().is_ok,
            keep_artifacts=args.keep_artifacts,
        )
        info_log(f"k6 退出码: {exit_code}")
        return exit_code

    ctx, tokens = prepare(scenario, password)
    auction_id = ctx["auctionId"]
    room_id = ctx["roomId"]
    info_log(
        f"已创建竞拍 {auction_id} (room={room_id}), "
        f"生成 {len(tokens)} 个出价人 token"
    )

    exit_code = 1
    try:
        exit_code = run_k6(
            scenario,
            auction_id,
            room_id,
            tokens,
            base_url,
            k6_bin,
            args.keep_artifacts,
            ws_url=ws_url,
            bid_destination=bid_destination,
        )
    finally:
        cleanup(ctx, auction_id, room_id)
    info_log(f"k6 退出码: {exit_code}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
