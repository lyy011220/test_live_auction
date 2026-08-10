"""WS 域 | 连接鉴权、订阅隔离和身份安全。"""
import allure
import pytest
import stomp
import time
from clients.auction_client import AuctionClient
from clients.bid_client import BidClient
from clients.room_client import RoomClient
from models.payloads import DEFAULT_AUCTION_PAYLOAD as P, AuctionPayload
from support.assertions import assert_fields, assert_ok, require_ok
from support.traceability import case
from ws.events import bid_event
from ws.stomp_client import StompWebSocketClient, bid_destination

pytestmark = pytest.mark.skipif(stomp is None, reason="stomp.py 未安装")

EPIC = allure.epic("直播竞拍平台")
FEATURE = allure.feature("WebSocket域")

START = P["startPrice"]
INC = P["incrementAmount"]
MAXP = P["maxPrice"]
MIN_VALID = START + INC

@EPIC
@FEATURE
@allure.story("WS-SEC-001")
@allure.severity(allure.severity_level.CRITICAL)
@allure.title("WS-SEC-001 STOMP 报文伪造 userId 不能写入")
@pytest.mark.ws
@pytest.mark.api
@case("WS-SEC-001")
def test_ws_sec_001_spoof_user_id(started_auction_with_bidder, make_bidder):
    """核心预期: 伪造身份不能写入、排名或触发 BID 广播。"""
    ctx = started_auction_with_bidder
    aid = ctx["auctionId"]
    room_id = ctx["roomId"]
    victim_id = ctx["bidderId"]  # 试图伪造为该用户
    attacker = make_bidder()     # 实际连接者 (攻击者)

    ws = StompWebSocketClient(token=attacker.token)
    try:
        ws.connect()
        ws.subscribe_auction_topic(room_id)

        # 清空历史消息后伪造 victim_id 通过 WS 发送出价
        ws.listener.clear()
        ws.send(bid_destination(), {"itemId": aid, "userId": victim_id, "amount": MIN_VALID})

        # 轮询确认伪造 userId 不触发 BID 广播 (超时未收到即通过)
        with pytest.raises(AssertionError, match="timeout"):
            ws.wait_for_message(bid_event(item_id=aid), timeout=5)

        # REST 验证价格/次数不变
        detail = AuctionClient(ctx["merchantClient"]).public_detail(aid)
        assert_fields(detail, {"bidCount": 0}, "伪造出价后终态")
    finally:
        ws.disconnect()

@EPIC
@FEATURE
@allure.story("WS-AUT-001")
@allure.severity(allure.severity_level.CRITICAL)
@allure.title("WS-AUT-001 缺失/无效令牌连接被拒绝")
@pytest.mark.ws
@pytest.mark.api
@case("WS-AUT-001")
def test_ws_aut_001_invalid_token_connect(live_room):
    """核心预期: 受保护连接拒绝无效令牌且不改变在线或交易状态。"""
    room_id = live_room["roomId"]
    room = RoomClient()
    before = require_ok(room.online_count(room_id), "连接前在线人数")
    count_before = (before.data or {}).get("online", 0)

    # 无 token 连接应被拒
    for label, token in [("无token", ""), ("无效token", "invalid_token_xyz")]:
        ws = StompWebSocketClient(token=token)
        try:
            rejected = False
            try:
                ws.connect()
            except Exception:
                rejected = True
            if not rejected:
                # connect 未抛异常, 等待异步 ERROR 帧
                time.sleep(0.5)
                rejected = bool(ws.listener.errors)
            assert rejected, f"{label}连接应被拒绝"
        finally:
            ws.disconnect()

    # 在线人数不变
    after = require_ok(room.online_count(room_id), "拒绝后在线人数")
    count_after = (after.data or {}).get("online", 0)
    assert count_after == count_before, (
        f"无效连接不应改变在线人数: {count_before} -> {count_after}"
    )

@EPIC
@FEATURE
@allure.story("WS-AUT-002")
@allure.severity(allure.severity_level.NORMAL)
@allure.title("WS-AUT-002 跨 room topic 订阅不泄露未鉴权事件")
@pytest.mark.ws
@pytest.mark.api
@case("WS-AUT-002")
def test_ws_aut_002_cross_room_topic(live_room, merchant_client, make_bidder, unique_name):
    """核心预期: 只订阅 roomA 时, roomB 的 BID 事件不泄露。"""
    room_a_id = live_room["roomId"]

    # 用另一个主播创建 roomB + 竞拍
    room_b = RoomClient(merchant_client)
    created_b = require_ok(room_b.create(title=unique_name("roomB")), "创建房间B")
    room_b_id = created_b.data["id"]
    require_ok(room_b.start(room_b_id), "开播房间B")
    payload = AuctionPayload().for_room(room_b_id).to_dict()
    auction_b = require_ok(AuctionClient(merchant_client).admin_create(payload), "创建竞拍B")
    aid_b = auction_b.data["id"]
    require_ok(AuctionClient(merchant_client).admin_start(aid_b), "开始竞拍B")

    bidder = make_bidder()
    ws = StompWebSocketClient(token=bidder.token)
    try:
        ws.connect()
        # 只订阅 roomA
        ws.subscribe_auction_topic(room_a_id)
        ws.listener.clear()

        # 在 roomB 出价
        assert_ok(BidClient(bidder).bid(aid_b, amount=MIN_VALID), "roomB 出价")

        # 轮询确认只订阅 roomA 时不泄露 roomB 的 BID (超时未收到即通过)
        with pytest.raises(AssertionError, match="timeout"):
            ws.wait_for_message(bid_event(item_id=aid_b), timeout=5)
    finally:
        ws.disconnect()

@EPIC
@FEATURE
@allure.story("WS-SEC-002")
@allure.severity(allure.severity_level.CRITICAL)
@allure.title("WS-SEC-002 WebSocket 正常出价触发 BID 广播")
@pytest.mark.ws
@pytest.mark.api
@case("WS-SEC-002")
def test_ws_sec_002_ws_bid_triggers_broadcast(started_auction_with_bidder, make_bidder):
    """核心预期: 通过 WS /app/bid 正常出价 (合法 userId) 触发 BID 广播。

    与 SEC-001 (伪造 userId) 互补: 验证合法 WS 出价与 REST 出价等效。
    """
    ctx = started_auction_with_bidder
    aid = ctx["auctionId"]
    room_id = ctx["roomId"]
    bidder = make_bidder()

    ws = StompWebSocketClient(token=bidder.token)
    try:
        ws.connect()
        ws.subscribe_auction_topic(room_id)

        # 通过 WS /app/bid 正常出价 (userId 来自 token, 合法)
        ws.send(bid_destination(), {"itemId": aid, "userId": bidder.user_id, "amount": MIN_VALID})

        # 等待 BID 广播
        msg = ws.wait_for_message(bid_event(item_id=aid, price=MIN_VALID), timeout=5)
        assert msg is not None, "WS 正常出价应触发 BID 广播"

        # REST 验证数据已写入
        detail = AuctionClient(ctx["merchantClient"]).public_detail(aid)
        assert_fields(detail, {"currentPrice": MIN_VALID, "bidCount": 1}, "WS 出价后终态")
    finally:
        ws.disconnect()
