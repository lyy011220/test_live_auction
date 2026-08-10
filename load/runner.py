"""k6 性能场景调度 (python -m load.runner --scenario <name>)。

流程: AuctionLifecycle 造一个已开始竞拍 -> 从用户池取 N 个出价人写 tokens.json ->
k6 run 注入 ITEM_ID/TOKENS_FILE/BASE_URL 并 --summary-export -> summarize 落盘 md。
临时 tokens.json 用完即清, k6 summary 与 md 保留在 reports/k6/。
出价人复用 reports/user_pool.json (与 pytest 共享), 池子不足或过期自动补充注册。
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from clients.auth_client import default_password
from commons.logger_util import info_log
from commons.yaml_util import read_config_yaml
from load.registry import SCENARIOS, get_scenario
from load.provenance import (
    backend_identity,
    metadata_path_for,
    write_run_metadata,
)
from load.summarize import (
    parse,
    summary_path_for,
    write_markdown,
)
from clients.auction_client import AuctionClient
from clients.room_client import RoomClient
from scenarios.auction_lifecycle import AuctionLifecycle
from support.user_pool import ensure_pool, get_bidders

ROOT = Path(__file__).resolve().parents[1]


def generate_tokens(count: int, password: str) -> list[dict]:
    """从用户池取 count 个 bidder (池子不足自动扩充)。"""
    pool = ensure_pool(password=password, bidder_count=max(count, 20))
    if len(pool["bidders"]) < count:
        # 池子不够, 重建更大的池子
        pool = ensure_pool(password=password, bidder_count=count, force=True)
    return get_bidders(pool, count)


def prepare(scenario, password: str) -> tuple[dict, list[dict]]:
    """造一个已开始竞拍 + N 个出价人 token，返回生命周期上下文和 tokens。"""
    ctx = AuctionLifecycle(password=password).create_started_auction(
        name=f"load-{scenario.name}"
    )
    tokens = generate_tokens(scenario.vus, password)
    return ctx, tokens


def run_k6(
    scenario,
    auction_id,
    room_id,
    tokens,
    base_url,
    k6_bin,
    keep,
    ws_url=None,
    bid_destination=None,
) -> int:
    runtime = Path(tempfile.mkdtemp(prefix="la_qa_"))
    try:
        token_file = runtime / "tokens.json"
        token_file.write_text(json.dumps(tokens, indent=2), encoding="utf-8")

        summary_path = summary_path_for(scenario.name)
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        for stale in (
            summary_path,
            metadata_path_for(scenario.name),
            summary_path.parent / f"{scenario.name}.md",
        ):
            stale.unlink(missing_ok=True)

        started_at = datetime.now(timezone.utc).isoformat()
        identity = backend_identity(base_url)
        cmd = [
            k6_bin, "run",
            "-e", f"ITEM_ID={auction_id}",
            "-e", f"ROOM_ID={room_id}",
            "-e", f"TOKENS_FILE={token_file}",
            "-e", f"BASE_URL={base_url}",
            "-e", f"WS_URL={ws_url or base_url.replace('http', 'ws', 1) + '/ws/websocket'}",
            "-e", f"BID_DESTINATION={bid_destination or '/app/bid'}",
            "--summary-export", str(summary_path),
            str(scenario.script),
        ]
        info_log(f"k6 命令: {' '.join(str(c) for c in cmd)}")
        try:
            rc = subprocess.run(cmd, cwd=str(ROOT), check=False).returncode
        except OSError as exc:
            info_log(f"k6 命令执行失败: {exc}")
            rc = 127

        if summary_path.exists():
            write_run_metadata(scenario.name, {
                "schema_version": 1,
                "scenario": scenario.name,
                "case_id": scenario.case_id,
                "base_url": base_url,
                "auction_id": auction_id,
                "room_id": room_id,
                "started_at": started_at,
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "k6_exit_code": rc,
                "backend": identity,
            })
            m = parse(summary_path)
            m["run"] = json.loads(metadata_path_for(scenario.name).read_text(encoding="utf-8"))
            write_markdown(scenario.name, m)
        return rc
    finally:
        if keep:
            info_log(f"临时文件保留: {runtime}")
        else:
            shutil.rmtree(runtime, ignore_errors=True)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="k6 性能场景调度")
    parser.add_argument("--scenario", choices=sorted(SCENARIOS), required=True)
    parser.add_argument("--k6", default=None, help="k6 可执行文件路径；默认读取 K6_BIN/config")
    parser.add_argument("--keep-artifacts", action="store_true", help="保留临时 tokens.json")
    args = parser.parse_args(argv)

    scenario = get_scenario(args.scenario)
    password = default_password()
    base_url = (read_config_yaml("BASE", "base_live_auction_url") or "http://localhost:8080").rstrip("/")
    ws_url = read_config_yaml("BASE", "ws_url") or base_url.replace("http", "ws", 1) + "/ws/websocket"
    bid_destination = read_config_yaml("STOMP", "bid_destination") or "/app/bid"
    k6_bin = args.k6 or read_config_yaml("K6", "bin") or "k6"

    ctx, tokens = prepare(scenario, password)
    auction_id = ctx["auctionId"]
    room_id = ctx["roomId"]
    info_log(f"已创建竞拍 {auction_id} (room={room_id}), 生成 {len(tokens)} 个出价人 token")

    rc = 1
    try:
        rc = run_k6(
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
        merchant = ctx["merchantClient"]
        try:
            AuctionClient(merchant).admin_cancel(auction_id, "qa load cleanup", name="清理压测竞拍")
        except Exception as exc:  # noqa: BLE001
            info_log(f"清理压测竞拍 {auction_id} 跳过: {exc}")
        try:
            RoomClient(merchant).stop(room_id, name="清理压测直播间")
        except Exception as exc:  # noqa: BLE001
            info_log(f"清理压测直播间 {room_id} 跳过: {exc}")
    info_log(f"k6 退出码: {rc}")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
