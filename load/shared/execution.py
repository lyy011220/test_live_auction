from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from clients.auction_client import AuctionClient
from clients.room_client import RoomClient
from commons.logger_util import info_log
from load.provenance import (
    backend_identity,
    metadata_path_for,
    write_run_metadata,
)
from load.summarize import parse, summary_path_for, write_markdown
from scenarios.auction_lifecycle import AuctionLifecycle
from support.user_pool import ensure_pool, get_bidders


ROOT = Path(__file__).resolve().parents[2]


def generate_tokens(count: int, password: str) -> list[dict]:
    pool = ensure_pool(password=password, bidder_count=max(count, 20))
    if len(pool["bidders"]) < count:
        pool = ensure_pool(password=password, bidder_count=count, force=True)
    return get_bidders(pool, count)


def prepare(scenario, password: str) -> tuple[dict, list[dict]]:
    auction_payload = {"name": f"load-{scenario.name}"}
    if scenario.auction_duration_minutes is not None:
        auction_payload["durationMinutes"] = scenario.auction_duration_minutes
    ctx = AuctionLifecycle(password=password).create_started_auction(
        **auction_payload
    )
    tokens = (
        generate_tokens(scenario.vus, password)
        if scenario.requires_tokens
        else []
    )
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
        command = [
            k6_bin,
            "run",
            "-e",
            f"ITEM_ID={auction_id}",
            "-e",
            f"ROOM_ID={room_id}",
            "-e",
            f"TOKENS_FILE={token_file}",
            "-e",
            f"BASE_URL={base_url}",
            "-e",
            f"WS_URL={ws_url or base_url.replace('http', 'ws', 1) + '/ws/websocket'}",
            "-e",
            f"BID_DESTINATION={bid_destination or '/app/bid'}",
            "--summary-export",
            str(summary_path),
            str(scenario.script),
        ]
        info_log(f"k6 命令: {' '.join(str(part) for part in command)}")
        try:
            exit_code = subprocess.run(
                command,
                cwd=str(ROOT),
                check=False,
            ).returncode
        except OSError as exc:
            info_log(f"k6 命令执行失败: {exc}")
            exit_code = 127

        if summary_path.exists():
            write_run_metadata(
                scenario.name,
                {
                    "schema_version": 1,
                    "scenario": scenario.name,
                    "case_id": scenario.case_id,
                    "base_url": base_url,
                    "auction_id": auction_id,
                    "room_id": room_id,
                    "started_at": started_at,
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                    "k6_exit_code": exit_code,
                    "backend": identity,
                },
            )
            metrics = parse(summary_path)
            metrics["run"] = json.loads(
                metadata_path_for(scenario.name).read_text(encoding="utf-8")
            )
            write_markdown(scenario.name, metrics)
        return exit_code
    finally:
        if keep:
            info_log(f"临时文件保留: {runtime}")
        else:
            shutil.rmtree(runtime, ignore_errors=True)


def cleanup(ctx: dict, auction_id: int, room_id: int) -> None:
    merchant = ctx["merchantClient"]
    try:
        AuctionClient(merchant).admin_cancel(
            auction_id,
            "qa load cleanup",
            name="清理压测竞拍",
        )
    except Exception as exc:  # noqa: BLE001
        info_log(f"清理压测竞拍 {auction_id} 跳过: {exc}")
    try:
        RoomClient(merchant).stop(room_id, name="清理压测直播间")
    except Exception as exc:  # noqa: BLE001
        info_log(f"清理压测直播间 {room_id} 跳过: {exc}")

