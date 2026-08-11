"""BID 域 | 鉴权、资源和竞拍状态限制。"""
import allure
import pytest

from clients.auction_client import AuctionClient
from clients.bid_client import BidClient
from clients.base import ApiClient
from clients.room_client import RoomClient
from models.enums import AuctionStatus, RoomStatus
from models.payloads import DEFAULT_AUCTION_PAYLOAD as P, AuctionPayload
from support.assertions import assert_failed, assert_fields, assert_ok, require_ok
from support.time_util import seconds_between, seconds_until
from support.traceability import case
from scenarios.auction_waits import wait_until_remaining
from support.wait_util import wait_until

EPIC = allure.epic("直播竞拍平台")
FEATURE = allure.feature("出价域")

START = P["startPrice"]          # 100
INC = P["incrementAmount"]       # 9
MAXP = P["maxPrice"]             # 1000
MIN_VALID = START + INC          # 109
MISSING_AUCTION_ID = 99999999

@EPIC
@FEATURE
@allure.story("BID-AUT-001")
@allure.severity(allure.severity_level.CRITICAL)
@allure.title("BID-AUT-001 未携带 Token 或 Token 无效/过期被拒绝")
@pytest.mark.bid
@pytest.mark.api
@case("BID-AUT-001")
def test_bid_aut_001_no_or_invalid_token(started_auction):
    """核心预期: 无 token 出价被拒且价格/次数/排名/记录不变。"""
    ctx = started_auction
    aid = ctx["auctionId"]
    anon = ApiClient()

    resp = BidClient(anon).bid(aid, amount=MIN_VALID)
    assert_failed(resp, "无 token 出价")

    # 验证终态不变
    detail = AuctionClient(ctx["merchantClient"]).public_detail(aid)
    assert_fields(detail, {"bidCount": 0}, "无token出价后终态")

@EPIC
@FEATURE
@allure.story("BID-AUT-002")
@allure.severity(allure.severity_level.CRITICAL)
@allure.title("BID-AUT-002 主播角色作为出价人被拒绝")
@pytest.mark.bid
@pytest.mark.api
@case("BID-AUT-002")
def test_bid_aut_002_merchant_bidder(started_auction, merchant_client):
    """核心预期: 主播 token 出价被拒且价格/次数/排名/记录不变。"""
    ctx = started_auction
    aid = ctx["auctionId"]

    resp = BidClient(merchant_client).bid(aid, amount=MIN_VALID)
    assert_failed(resp, "主播角色出价")

    # 验证终态不变
    detail = AuctionClient(ctx["merchantClient"]).public_detail(aid)
    assert_fields(detail, {"bidCount": 0}, "主播出价后终态")

@EPIC
@FEATURE
@allure.story("BID-RES-001")
@allure.severity(allure.severity_level.NORMAL)
@allure.title("BID-RES-001 对不存在竞拍出价返回资源不存在")
@pytest.mark.bid
@pytest.mark.api
@case("BID-RES-001")
def test_bid_res_001_missing_auction(bidder_client):
    """核心预期: 不存在 auctionId 出价被拒且不写入数据。"""
    resp = BidClient(bidder_client).bid(MISSING_AUCTION_ID, amount=MIN_VALID)
    assert_failed(resp, "对不存在竞拍出价")

@EPIC
@FEATURE
@allure.story("BID-STA-001")
@allure.severity(allure.severity_level.CRITICAL)
@allure.title("BID-STA-001 对已取消竞拍出价被拒绝")
@pytest.mark.bid
@pytest.mark.api
@case("BID-STA-001")
def test_bid_sta_001_bid_cancelled(started_auction_with_bidder, make_bidder):
    """核心预期: 取消竞拍后出价被拒且价格/出价人/次数/记录不变。"""
    ctx = started_auction_with_bidder
    merchant = ctx["merchantClient"]
    aid = ctx["auctionId"]

    require_ok(AuctionClient(merchant).admin_cancel(aid, "test"), "取消竞拍")

    resp = BidClient(make_bidder()).bid(aid, amount=MIN_VALID)
    assert_failed(resp, "已取消竞拍出价")

    # 验证终态不变: status=CANCELLED, bidCount=0
    detail = AuctionClient(merchant).public_detail(aid)
    assert_fields(detail, {"status": AuctionStatus.CANCELLED, "bidCount": 0}, "取消后终态")

@EPIC
@FEATURE
@allure.story("BID-STA-002")
@allure.severity(allure.severity_level.CRITICAL)
@allure.title("BID-STA-002 竞拍未开始时出价被拒绝")
@pytest.mark.bid
@pytest.mark.api
@case("BID-STA-002")
def test_bid_sta_002_bid_not_started(pending_auction, make_bidder):
    """核心预期: 待开始竞拍出价被拒且价格/出价人/次数/记录不变。"""
    ctx = pending_auction
    aid = ctx["auctionId"]

    resp = BidClient(make_bidder()).bid(aid, amount=MIN_VALID)
    assert_failed(resp, "未开始竞拍出价")

    # 验证终态不变: status=PENDING, bidCount=0
    detail = AuctionClient(ctx["merchantClient"]).public_detail(aid)
    assert_fields(detail, {"status": AuctionStatus.PENDING, "bidCount": 0}, "未开始终态")

@EPIC
@FEATURE
@allure.story("BID-STA-003")
@allure.severity(allure.severity_level.NORMAL)
@allure.title("BID-STA-003 自然结束或流拍后出价被拒绝")
@pytest.mark.slow  # 标记慢速测试
@pytest.mark.bid
@pytest.mark.api
@case("BID-STA-003")
def test_bid_sta_003_bid_after_ended(live_room, make_bidder):
    """核心预期: 竞拍自然到期后出价被拒且终态数据不变。

    用 durationMinutes=1 缩短等待, 轮询 public_detail.status 直到 ENDED (替代固定 sleep)。
    """
    merchant, room_id = live_room["merchantClient"], live_room["roomId"]
    payload = AuctionPayload(durationMinutes=1).for_room(room_id).to_dict()
    created = require_ok(AuctionClient(merchant).admin_create(payload), "创建短时竞拍")
    aid = created.data["id"]
    require_ok(AuctionClient(merchant).admin_start(aid), "开始竞拍")

    # 轮询等待自然到期 (durationMinutes=1, 留 15s 余量), 到期即提前返回
    def status():
        return (AuctionClient(merchant).public_detail(aid).data or {}).get("status")
    wait_until(status, predicate=lambda s: s == AuctionStatus.ENDED, timeout=75, interval=1.0)
    assert status() == AuctionStatus.ENDED, "竞拍应已自然到期 (ENDED)"

    resp = BidClient(make_bidder()).bid(aid, amount=MIN_VALID)
    assert_failed(resp, "竞拍到期后出价")

    # 验证终态: status=ENDED (自然到期), bidCount=0
    detail = AuctionClient(merchant).public_detail(aid)
    assert_fields(detail, {"status": AuctionStatus.ENDED, "bidCount": 0}, "到期后终态")

@EPIC
@FEATURE
@allure.story("BID-STA-006")
@allure.severity(allure.severity_level.NORMAL)
@allure.title("BID-STA-006 下播后进行中竞拍出价被拒绝")
@pytest.mark.bid
@pytest.mark.api
@case("BID-STA-006")
def test_bid_sta_006_bid_after_room_stop(live_room, make_bidder):
    """核心预期: 房间下播后出价被拒, 且竞拍价格与次数不变。"""
    merchant, room_id = live_room["merchantClient"], live_room["roomId"]
    room = RoomClient(merchant)

    payload = AuctionPayload().for_room(room_id).to_dict()
    created = require_ok(AuctionClient(merchant).admin_create(payload), "创建竞拍")
    aid = created.data["id"]
    require_ok(AuctionClient(merchant).admin_start(aid), "开始竞拍")
    before = require_ok(AuctionClient(merchant).public_detail(aid), "下播前竞拍详情")
    before_data = before.data or {}
    require_ok(room.stop(room_id), "下播")

    my_room = require_ok(room.get_my_room(), "查询下播后房间")
    assert_fields(my_room, {"id": room_id, "status": RoomStatus.ENDED}, "下播后房间")

    resp = BidClient(make_bidder()).bid(aid, amount=MIN_VALID)
    assert_failed(resp, "房间下播后出价")

    # 不依赖后端下播后的竞拍状态码, 只验证业务数据无副作用
    after = require_ok(AuctionClient(merchant).public_detail(aid), "下播后竞拍详情")
    after_data = after.data or {}
    assert after_data.get("currentPrice") == before_data.get("currentPrice"), "拒绝出价后价格不得变化"
    assert after_data.get("bidCount") == before_data.get("bidCount"), "拒绝出价后次数不得变化"

@EPIC
@FEATURE
@allure.story("BID-STA-007")
@allure.severity(allure.severity_level.NORMAL)
@allure.title("BID-STA-007 自然到期临界时刻出价成功且触发延迟")
@pytest.mark.slow  # 标记慢速测试
@pytest.mark.bid
@pytest.mark.api
@case("BID-STA-007")
def test_bid_sta_007_snipe_bid_triggers_delay(live_room, make_bidder):
    """核心预期: 临近结束出价成功, 且结束时间按"出价时刻 + delaySeconds"延后 (非原结束时间+delay)。

    用 durationMinutes=1, delaySeconds=10; 轮询进入延时窗口后半段 (剩余≈delay/2) 后出价,
    再轮询等到延时后自然结束, 用 actualEndTime - plannedEndTime 校验延时模型:
      - 延时基于出价时刻: extension = delay - remaining_at_bid ∈ (0, delay)
      - 若后端误用"原结束时间+delay": extension == delay (被捕获)
      - 若未触发延时: extension == 0 (被捕获)
    (plannedEndTime 不随延时更新, 故延时后读 actualEndTime 才是新结束时间。)
    """
    DELAY = 10
    merchant, room_id = live_room["merchantClient"], live_room["roomId"]
    payload = AuctionPayload(durationMinutes=1, delaySeconds=DELAY).for_room(room_id).to_dict()
    created = require_ok(AuctionClient(merchant).admin_create(payload), "创建短时竞拍")
    aid = created.data["id"]
    require_ok(AuctionClient(merchant).admin_start(aid), "开始竞拍")

    # 原结束时间 (start 后才有 plannedEndTime)
    end_before = (AuctionClient(merchant).public_detail(aid).data or {}).get("plannedEndTime")
    assert end_before, "plannedEndTime 缺失"

    # 轮询进入延时窗口后半段 (剩余 <= DELAY/2), 而非固定 sleep
    wait_until_remaining(aid, target_remaining=DELAY // 2, client=merchant)
    remaining_at_bid = seconds_until(end_before)

    # 临界出价
    resp = BidClient(make_bidder()).bid(aid, amount=MIN_VALID)
    assert_ok(resp, "临近结束出价")

    # 轮询等到延时后自然结束, 读取 actualEndTime
    def status():
        return (AuctionClient(merchant).public_detail(aid).data or {}).get("status")
    wait_until(status, predicate=lambda s: s == AuctionStatus.ENDED, timeout=DELAY + 20, interval=1.0)
    actual_end = (AuctionClient(merchant).public_detail(aid).data or {}).get("actualEndTime")
    assert actual_end, "actualEndTime 缺失"

    # 延时基于出价时刻: extension = delay - remaining_at_bid, 应落在 (0, delay)
    extension = seconds_between(actual_end, end_before)
    assert 0 < extension < DELAY, (
        f"延时应基于出价时刻 (extension ∈ (0, {DELAY})): 实际 {extension:.1f}s "
        f"(出价时剩余 {remaining_at_bid:.1f}s); "
        f"若≈0 说明未触发延时, 若≈{DELAY} 说明后端误用'原结束时间+delay'模型"
    )