from __future__ import annotations

import argparse

from clients.auth_client import default_password
from commons.logger_util import info_log
from commons.yaml_util import read_config_yaml
from load.concurrency.registry import SCENARIOS, get_scenario
from load.shared.execution import cleanup, prepare, run_k6


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="k6 并发正确性场景调度")
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

