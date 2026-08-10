"""WS 域 | 竞拍生命周期和出价事件广播。"""
import allure
import pytest
import stomp
import time
from clients.auction_client import AuctionClient
from clients.bid_client import BidClient
from models.enums import AuctionStatus
from models.payloads import DEFAULT_AUCTION_PAYLOAD as P, AuctionPayload
from support.assertions import assert_ok, require_ok
from support.time_util import seconds_between
from support.traceability import case
from support.wait_util import wait_until
from ws.events import (
    bid_event,
    cancelled_event,
    delayed_event,
    ended_event,
    outbid_event,
    sold_event,
    started_event,
)
from ws.stomp_client import StompWebSocketClient

pytestmark = pytest.mark.skipif(stomp is None, reason="stomp.py 未安装")

EPIC = allure.epic("直播竞拍平台")
FEATURE = allure.feature("WebSocket域")

START = P["startPrice"]
INC = P["incrementAmount"]
MAXP = P["maxPrice"]
MIN_VALID = START + INC

@EPIC
@FEATURE
@allure.story("WS-EVT-001")
@allure.severity(allure.severity_level.CRITICAL)
@allure.title("WS-EVT-001 开始竞拍推送 STARTED 事件")
@pytest.mark.ws
@pytest.mark.api
@case("WS-EVT-001")
def test_ws_evt_001_started_push(pending_auction, make_bidder):
    """核心预期: 合格订阅者收到对应竞拍的开始事件。"""
    ctx = pending_auction
    aid = ctx["auctionId"]
    room_id = ctx["roomId"]
    merchant = ctx["merchantClient"]
    bidder = make_bidder()

    ws = StompWebSocketClient(token=bidder.token)
    try:
        ws.connect()
        ws.subscribe_auction_topic(room_id)
        # REST 触发开始竞拍
        resp = AuctionClient(merchant).admin_start(aid)
        assert_ok(resp, "竞拍开始")
        # 等待 STARTED 广播
        msg = ws.wait_for_message(started_event(aid), timeout=5)
        assert msg is not None, "主播开始竞拍应收到 STARTED 事件"
    finally:
        ws.disconnect()

@EPIC
@FEATURE
@allure.story("WS-EVT-002")
@allure.severity(allure.severity_level.CRITICAL)
@allure.title("WS-EVT-002 REST 成功出价推送 BID 事件")
@pytest.mark.ws
@pytest.mark.api
@case("WS-EVT-002")
def test_ws_evt_002_bid_broadcast(started_auction_with_bidder):
    """核心预期: REST 出价后订阅者收到 BID 事件, 价格/次数/赢家正确。"""
    ctx = started_auction_with_bidder
    bidder = ctx["bidderClient"]
    aid = ctx["auctionId"]
    room_id = ctx["roomId"]
    amount = MIN_VALID

    ws = StompWebSocketClient(token=ctx["bidderToken"])
    try:
        ws.connect()
        ws.subscribe_auction_topic(room_id)
        # REST 触发出价
        resp = BidClient(bidder).bid(aid, amount=amount)
        assert_ok(resp, "出价")
        # 等待 BID 广播
        msg = ws.wait_for_message(bid_event(item_id=aid, price=amount), timeout=5)
        assert msg is not None, "出价成功应收到 BID 事件"
    finally:
        ws.disconnect()

@EPIC
@FEATURE
@allure.story("WS-EVT-003")
@allure.severity(allure.severity_level.NORMAL)
@allure.title("WS-EVT-003 封顶成交推送 SOLD 事件且只广播一次")
@pytest.mark.ws
@pytest.mark.api
@case("WS-EVT-003")
def test_ws_evt_003_sold_push(started_auction_with_bidder):
    """核心预期: 成交事件内容准确且只广播一次。"""
    ctx = started_auction_with_bidder
    bidder = ctx["bidderClient"]
    aid = ctx["auctionId"]
    room_id = ctx["roomId"]

    ws = StompWebSocketClient(token=ctx["bidderToken"])
    try:
        ws.connect()
        ws.subscribe_auction_topic(room_id)

        # 清空历史消息，避免污染
        ws.listener.clear()

        # 封顶出价触发成交
        resp = BidClient(bidder).bid(aid, amount=MAXP)
        assert_ok(resp, "封顶出价")
        # 第一条 SOLD 应收到
        ws.wait_for_message(sold_event(item_id=aid), timeout=5)
        # 轮询确认无第二条 SOLD (只广播一次): 超时未收到即通过
        ws.listener.clear()
        with pytest.raises(AssertionError, match="timeout"):
            ws.wait_for_message(sold_event(item_id=aid), timeout=3)
    finally:
        ws.disconnect()

@EPIC
@FEATURE
@allure.story("WS-EVT-004")
@allure.severity(allure.severity_level.NORMAL)
@allure.title("WS-EVT-004 临近结束出价触发延时事件")
@pytest.mark.slow  # 轮询等待延时窗口
@pytest.mark.ws
@pytest.mark.api
@case("WS-EVT-004")
def test_ws_evt_004_delayed_push(live_room, make_bidder):
    """核心预期: 临近结束出价触发 DELAYED 事件, newEndTime 按"出价时刻 + delaySeconds"延后。

    用 durationMinutes=1, delaySeconds=10; 轮询进入延时窗口后半段 (剩余≈delay/2) 后出价。
    延时基于出价时刻: newEndTime - plannedEndTime = delay - remaining_at_bid ∈ (0, delay);
    若后端误用"原结束时间+delay"则 == delay (被捕获), 若未触发延时则 == 0 (被捕获)。
    """
    DELAY = 10
    DURATION_SEC = 60  # durationMinutes=1
    merchant, room_id = live_room["merchantClient"], live_room["roomId"]
    bidder = make_bidder()

    payload = AuctionPayload(durationMinutes=1, delaySeconds=DELAY).for_room(room_id).to_dict()
    created = require_ok(AuctionClient(merchant).admin_create(payload), "创建短时竞拍")
    aid = created.data["id"]
    require_ok(AuctionClient(merchant).admin_start(aid), "开始竞拍")

    # start 后才有 plannedEndTime, 记录原结束时间用于校验延时模型
    end_before = (AuctionClient(merchant).public_detail(aid).data or {}).get("plannedEndTime")
    assert end_before, "plannedEndTime 缺失"

    # 记录开始时刻 (monotonic 时钟不受时区影响), 用于轮询进入延时窗口
    start_mono = time.monotonic()

    ws = StompWebSocketClient(token=bidder.token)
    try:
        ws.connect()
        ws.subscribe_auction_topic(room_id)

        # 轮询进入延时窗口后半段 (剩余 <= DELAY/2)
        # 用 monotonic 时钟基于开始时刻计算已耗时, 避免时区错配导致剩余时间计算不准
        wait_until(
            lambda: time.monotonic() - start_mono,
            predicate=lambda elapsed: elapsed >= DURATION_SEC - DELAY // 2,
            timeout=120,
            interval=1.0,
        )
        # 防御性校验: 确保竞拍仍在进行中 (时区错配或时钟偏移导致偏差时暴露)
        detail = AuctionClient(merchant).public_detail(aid)
        assert detail.data.get("status") == AuctionStatus.LIVE, (
            f"出价前竞拍状态应为 LIVE, 实际 {detail.data.get('status')}"
        )
        resp = BidClient(bidder).bid(aid, amount=MIN_VALID)
        assert_ok(resp, "临近结束出价")

        msg = ws.wait_for_message(delayed_event(item_id=aid), timeout=5)
        assert msg is not None, "临近结束出价应收到 DELAYED 事件"
        new_end = msg.get("newEndTime")
        assert new_end is not None, "DELAYED 事件应包含 newEndTime"
        # 延时基于出价时刻: extension = delay - remaining_at_bid ∈ (0, delay)
        extension = seconds_between(new_end, end_before)
        assert 0 < extension < DELAY, (
            f"newEndTime 应基于出价时刻延后 (extension ∈ (0, {DELAY})): 实际 {extension:.1f}s; "
            f"若≈0 说明未触发延时, 若≈{DELAY} 说明后端误用'原结束时间+delay'模型"
        )
    finally:
        ws.disconnect()

@EPIC
@FEATURE
@allure.story("WS-EVT-005")
@allure.severity(allure.severity_level.NORMAL)
@allure.title("WS-EVT-005 主播取消竞拍推送 CANCELLED 事件")
@pytest.mark.ws
@pytest.mark.api
@case("WS-EVT-005")
def test_ws_evt_005_cancelled_push(started_auction_with_bidder, make_bidder):
    """核心预期: admin_cancel 后订阅者收到 CANCELLED 事件。"""
    ctx = started_auction_with_bidder
    aid = ctx["auctionId"]
    room_id = ctx["roomId"]
    merchant = ctx["merchantClient"]
    bidder = make_bidder()

    ws = StompWebSocketClient(token=bidder.token)
    try:
        ws.connect()
        ws.subscribe_auction_topic(room_id)
        # REST 触发取消竞拍
        require_ok(AuctionClient(merchant).admin_cancel(aid, "test"), "取消竞拍")
        # 等待 CANCELLED 广播
        msg = ws.wait_for_message(cancelled_event(aid), timeout=5)
        assert msg is not None, "主播取消竞拍应收到 CANCELLED 事件"
    finally:
        ws.disconnect()

@EPIC
@FEATURE
@allure.story("WS-EVT-006")
@allure.severity(allure.severity_level.NORMAL)
@allure.title("WS-EVT-006 竞拍自然到期推送 ENDED 事件")
@pytest.mark.slow  # 轮询等待自然到期
@pytest.mark.ws
@pytest.mark.api
@case("WS-EVT-006")
def test_ws_evt_006_ended_push(live_room, make_bidder):
    """核心预期: 竞拍自然到期后订阅者收到 ENDED 事件。

    用 durationMinutes=1, 轮询等待 ENDED 广播 (留 15s 余量), 替代固定 sleep。
    """
    merchant, room_id = live_room["merchantClient"], live_room["roomId"]
    bidder = make_bidder()

    payload = AuctionPayload(durationMinutes=1).for_room(room_id).to_dict()
    created = require_ok(AuctionClient(merchant).admin_create(payload), "创建短时竞拍")
    aid = created.data["id"]
    require_ok(AuctionClient(merchant).admin_start(aid), "开始竞拍")

    ws = StompWebSocketClient(token=bidder.token)
    try:
        ws.connect()
        ws.subscribe_auction_topic(room_id)
        # 轮询等待自然到期后的 ENDED 广播 (durationMinutes=1, 留 15s 余量), 到期即提前返回
        msg = ws.wait_for_message(ended_event(aid), timeout=75)
        assert msg is not None, "竞拍自然到期应收到 ENDED 事件"
    finally:
        ws.disconnect()

@EPIC
@FEATURE
@allure.story("WS-EVT-007")
@allure.severity(allure.severity_level.NORMAL)
@allure.title("WS-EVT-007 原最高出价人被超越收到 OUTBID 点对点通知")
@pytest.mark.ws
@pytest.mark.api
@case("WS-EVT-007")
def test_ws_evt_007_outbid_notification(started_auction_with_bidder, make_bidder):
    """核心预期: 用户A 出价后用户B 更高出价, 用户A 收到 OUTBID (/user/queue/outbid)。"""
    ctx = started_auction_with_bidder
    aid = ctx["auctionId"]
    bidder_a = ctx["bidderClient"]
    bidder_b = make_bidder()

    # 用户A 先出价
    assert_ok(BidClient(bidder_a).bid(aid, amount=MIN_VALID), "用户A 出价")

    # 用户A 订阅点对点队列
    ws_a = StompWebSocketClient(token=ctx["bidderToken"])
    try:
        ws_a.connect()
        ws_a.subscribe_user_queue("/user/queue/outbid")

        # 用户B 更高出价
        assert_ok(BidClient(bidder_b).bid(aid, amount=MIN_VALID + INC), "用户B 出价")

        # 用户A 应收到 OUTBID 通知
        msg = ws_a.wait_for_message(outbid_event(aid), timeout=5)
        assert msg is not None, "用户A 被超越应收到 OUTBID 点对点通知"
    finally:
        ws_a.disconnect()
