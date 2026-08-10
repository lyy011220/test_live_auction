"""用户池: session 级复用已注册 bidder, pytest 与 k6 共享。

池子文件 reports/user_pool.json, 首次运行自动注册 20 个普通用户。
JWT exp 过期(7天)后自动重建。

主播不复用: 后端限制一个主播只能建一个直播间 (重复建房 400),
故主播仍由各用例 function 级注册。
"""
from __future__ import annotations

import base64
import json
import time
from pathlib import Path
from clients.auth_client import default_password, register_bidder
from clients.base import ApiClient
from commons.logger_util import info_log

POOL_PATH = Path(__file__).resolve().parents[1] / "reports" / "user_pool.json"
BIDDER_COUNT = 20
# 探活接口: bidder (role=2) 鉴权 GET, 有效 token 返回 200, 失效 token 返回 401
PROBE_PATH = "/api/user/bids"


def _decode_exp(token: str) -> float:
    """解码 JWT exp, 失败返回 0。"""
    parts = token.split(".")
    if len(parts) != 3:
        return 0.0
    payload = parts[1] + "=" * (-len(parts[1]) % 4)
    try:
        data = json.loads(base64.urlsafe_b64decode(payload.encode("ascii")).decode("utf-8"))
        return float(data.get("exp", 0))
    except Exception:
        return 0.0


def _probe_token(token: str) -> bool:
    """探活: 用 token 调一个 bidder 鉴权接口, 判断后端是否仍接受该 token。

    仅当后端明确回 401 (未登录/token 失效) 才返回 False, 由此触发 ensure_pool 重建;
    其余情况 (200/403/5xx 或网络异常) 返回 True——避免后端不可达或临时故障时反复重建。
    """
    if not token:
        return False
    try:
        resp = ApiClient(token=token).get(PROBE_PATH, name="用户池探活")
    except Exception:
        return True
    return resp.http_status != 401


def _is_valid(pool: dict | None) -> bool:
    """池子非空且首个 token 未过期(留 60s 缓冲), 且后端仍接受该 token。

    仅看 exp 无法发现"签名密钥轮换"导致的失效 (exp 未到但后端已拒认),
    故 exp 通过后再探活一次: 401 则判失效, 触发 ensure_pool 重建。
    """
    if not pool or not pool.get("bidders"):
        return False
    first = pool["bidders"][0]
    if _decode_exp(first.get("token", "")) <= time.time() + 60:
        return False
    return _probe_token(first.get("token", ""))


def _build_pool(bidder_count: int, password: str) -> dict:
    info_log(f"注册 {bidder_count} 个普通用户到用户池...")
    bidders = []
    for i in range(bidder_count):
        client = register_bidder(password=password)
        if not client.token or client.user_id is None:
            raise RuntimeError(f"bidder {i + 1} 注册失败, 缺 token/userId")
        bidders.append({
            "userid": client.user_id,
            "token": client.token,
            "username": client.username,
        })
    info_log(f"用户池就绪: {len(bidders)} 个普通用户")
    return {"generated_at": time.time(), "bidders": bidders}


def ensure_pool(path: Path = POOL_PATH, password: str | None = None,
                bidder_count: int = BIDDER_COUNT, force: bool = False) -> dict:
    """池子不存在或过期则创建, 否则复用。force=True 强制重建。"""
    password = password or default_password()
    if path.exists() and not force:
        try:
            pool = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pool = None
        if _is_valid(pool):
            return pool
    pool = _build_pool(bidder_count, password)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(pool, indent=2, ensure_ascii=False), encoding="utf-8")
    return pool


def load_pool(path: Path = POOL_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def get_bidder(pool: dict, index: int = 0) -> ApiClient:
    """从池子取第 index 个 bidder, 返回带 token 的 ApiClient。"""
    if index < 0 or index >= len(pool["bidders"]):
        raise IndexError(f"bidder 用户池索引越界: {index}/{len(pool['bidders'])}")
    entry = pool["bidders"][index]
    client = ApiClient(token=entry["token"])
    client.user_id = entry["userid"]
    client.username = entry["username"]
    return client


def extend_pool(pool: dict, password: str, path: Path = POOL_PATH) -> None:
    """追加一个 bidder 并持久化，供 session 分配器耗尽时扩容。"""
    client = register_bidder(password=password)
    if not client.token or client.user_id is None:
        raise RuntimeError("扩容 bidder 用户池失败，缺少 token/userId")
    pool["bidders"].append({
        "userid": client.user_id,
        "token": client.token,
        "username": client.username,
    })
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(pool, indent=2, ensure_ascii=False), encoding="utf-8")


def get_bidders(pool: dict, count: int) -> list[dict]:
    """取前 count 个 bidder 原始记录 (供 k6 tokens.json)。"""
    return pool["bidders"][:count]


def _main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="生成/刷新用户池")
    parser.add_argument("--force", action="store_true", help="强制重建")
    parser.add_argument("--count", type=int, default=BIDDER_COUNT, help="bidder 数量")
    args = parser.parse_args()
    pool = ensure_pool(bidder_count=args.count, force=args.force)
    print(f"用户池: {len(pool['bidders'])} 个普通用户 -> {POOL_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
