"""AUC 域 | 竞拍创建、查询与状态流转。"""
import allure
import pytest

from clients.auction_client import AuctionClient
from clients.bid_client import BidClient
from clients.room_client import RoomClient
from models.enums import AuctionStatus
from models.payloads import AuctionPayload
from support.assertions import assert_failed, assert_fields, assert_ok, require_ok
from support.traceability import case

EPIC = allure.epic("直播竞拍平台")
FEATURE = allure.feature("竞拍域")

MISSING_ROOM_ID = 99999999
MISSING_AUCTION_ID = 99999999


def _room_auction_ids(client, room_id):
    response = require_ok(AuctionClient(client).room_auctions(room_id), "查询房间竞拍列表")
    data = response.data or []
    if isinstance(data, dict):
        data = data.get("records") or data.get("content") or data.get("items") or []
    assert isinstance(data, list), f"房间竞拍列表应为 list，实际 {type(data).__name__}"
    return {item.get("id") for item in data if isinstance(item, dict)}

@EPIC
@FEATURE
@allure.story("AUC-STA-001")
@allure.severity(allure.severity_level.CRITICAL)
@allure.title("AUC-STA-001 房间未开播时创建竞拍被拒绝")
@pytest.mark.auction
@pytest.mark.api
@case("AUC-STA-001")
def test_auc_sta_001_create_when_room_not_live(merchant_client, unique_name):
    """核心预期: 房间未开播时创建竞拍被拒绝, 无竞拍落库。"""
    room = RoomClient(merchant_client)
    created = require_ok(room.create(title=unique_name("room")), "创建房间")
    rid = created.data["id"]
    # 不 start, 直接建竞拍
    resp = AuctionClient(merchant_client).admin_create(
        AuctionPayload().for_room(rid).to_dict()
    )
    assert_failed(resp, "未开播建竞拍")
    # 无竞拍落库: 该房间竞拍列表应为空
    auctions = AuctionClient(merchant_client).room_auctions(rid)
    assert not (auctions.data), "未开播房间不应有竞拍落库"

@EPIC
@FEATURE
@allure.story("AUC-NOR-001")
@allure.severity(allure.severity_level.CRITICAL)
@allure.title("AUC-NOR-001 直播中房间创建待开始竞拍且初始价等于底价")
@pytest.mark.auction
@pytest.mark.api
@case("AUC-NOR-001")
def test_auc_nor_001_create_auction(live_room):
    """核心预期: 直播中房间创建竞拍, 状态待开始(1), 初始价等于底价。"""
    merchant = live_room["merchantClient"]
    room_id = live_room["roomId"]
    payload = AuctionPayload().for_room(room_id).to_dict()
    resp = AuctionClient(merchant).admin_create(payload)
    assert_ok(resp, "创建竞拍")
    data = resp.data or {}
    assert data.get("id"), "应返回竞拍 id"
    assert_fields(resp, {"status": AuctionStatus.PENDING, "startPrice": payload["startPrice"]}, "新建竞拍")

@EPIC
@FEATURE
@allure.story("AUC-NOR-002")
@allure.severity(allure.severity_level.NORMAL)
@allure.title("AUC-NOR-002 修改未开始竞拍规则")
@pytest.mark.auction
@pytest.mark.api
@case("AUC-NOR-002")
def test_auc_nor_002_update_pending_rules(live_room):
    """核心预期: 允许修改未开始竞拍规则且持久化。"""
    merchant = live_room["merchantClient"]
    rid = live_room["roomId"]
    created = require_ok(
        AuctionClient(merchant).admin_create(AuctionPayload().for_room(rid).to_dict()),
        "创建竞拍",
    )
    aid = created.data["id"]

    resp = AuctionClient(merchant).admin_update(aid, {"incrementAmount": 20})
    assert_ok(resp, "修改未开始竞拍规则")

    detail = require_ok(AuctionClient(merchant).admin_detail(aid), "查询详情")
    assert detail.data.get("incrementAmount") == 20, (
        f"修改后 incrementAmount 期望 20, 实际 {detail.data.get('incrementAmount')}"
    )

@EPIC
@FEATURE
@allure.story("AUC-LST-001")
@allure.severity(allure.severity_level.NORMAL)
@allure.title("AUC-LST-001 主播竞拍列表包含自己创建的竞拍")
@pytest.mark.auction
@pytest.mark.api
@case("AUC-LST-001")
def test_auc_lst_001_admin_list_contains_created_auction(pending_auction):
    ctx = pending_auction
    resp = require_ok(
        AuctionClient(ctx["merchantClient"]).admin_list(page=1, size=100),
        "查询主播竞拍列表",
    )
    data = resp.data or {}
    records = data if isinstance(data, list) else (
        data.get("records") or data.get("content") or data.get("list") or data.get("items") or []
    )
    assert isinstance(records, list), f"竞拍列表记录应为 list，实际 data={data}"
    matched = [item for item in records if item.get("id") == ctx["auctionId"]]
    assert matched, f"主播竞拍列表应包含本轮创建的竞拍 {ctx['auctionId']}"
    assert matched[0].get("roomId") == ctx["roomId"], "列表中的竞拍应属于本轮直播间"

@EPIC
@FEATURE
@allure.story("AUC-STA-002")
@allure.severity(allure.severity_level.CRITICAL)
@allure.title("AUC-STA-002 开始竞拍进入进行中状态")
@pytest.mark.auction
@pytest.mark.api
@case("AUC-STA-002")
def test_auc_sta_002_start_auction(pending_auction):
    """核心预期: 开始竞拍后状态进入进行中(LIVE=2)。"""
    client = pending_auction["merchantClient"]
    aid = pending_auction["auctionId"]
    resp = AuctionClient(client).admin_start(aid)
    assert_ok(resp, "开始竞拍")
    detail = AuctionClient(client).admin_detail(aid)
    assert_ok(detail, "获取竞拍详情")
    assert detail.data.get("status") == AuctionStatus.LIVE, (
        f"开始后应为竞拍中(2), 实际 {detail.data.get('status')}"
    )

@EPIC
@FEATURE
@allure.story("AUC-STA-003")
@allure.severity(allure.severity_level.NORMAL)
@allure.title("AUC-STA-003 取消竞拍进入已取消状态且后续不可出价")
@pytest.mark.auction
@pytest.mark.api
@case("AUC-STA-003")
def test_auc_sta_003_cancel_auction(started_auction_with_bidder):
    """核心预期: 竞拍进入已取消状态(5)且后续出价被拒。"""
    ctx = started_auction_with_bidder
    merchant = ctx["merchantClient"]
    aid = ctx["auctionId"]
    bidder = ctx["bidderClient"]

    resp = AuctionClient(merchant).admin_cancel(aid, "test cancel")
    assert_ok(resp, "取消竞拍")
    detail = require_ok(AuctionClient(merchant).admin_detail(aid), "查询详情")
    assert detail.data.get("status") == AuctionStatus.CANCELLED, (
        f"取消后应为已取消(5), 实际 {detail.data.get('status')}"
    )

    # 取消后不可出价
    bid_resp = BidClient(bidder).bid(aid, amount=110)
    assert_failed(bid_resp, "已取消竞拍出价")

@EPIC
@FEATURE
@allure.story("AUC-STA-004")
@allure.severity(allure.severity_level.NORMAL)
@allure.title("AUC-STA-004 已启动竞拍修改规则被拒绝")
@pytest.mark.auction
@pytest.mark.api
@case("AUC-STA-004")
def test_auc_sta_004_update_live_rules(started_auction):
    """核心预期: 进行中竞拍 admin_update 被拒绝, 规则不变。"""
    merchant = started_auction["merchantClient"]
    aid = started_auction["auctionId"]

    resp = AuctionClient(merchant).admin_update(aid, {"incrementAmount": 15})
    assert_failed(resp, "进行中修改规则")
    # 验证规则未变 (原值 9)
    detail = require_ok(AuctionClient(merchant).admin_detail(aid), "查询详情")
    assert detail.data.get("incrementAmount") != 15, "进行中竞拍规则不应被修改"

@EPIC
@FEATURE
@allure.story("AUC-STA-005")
@allure.severity(allure.severity_level.NORMAL)
@allure.title("AUC-STA-005 重复启动、重复取消及启动后取消")
@pytest.mark.auction
@pytest.mark.api
@case("AUC-STA-005")
def test_auc_sta_005_repeat_state_change(started_auction):
    """核心预期: 重复 start/cancel 被拒绝, 不二次操作。"""
    merchant = started_auction["merchantClient"]
    aid = started_auction["auctionId"]

    # 1. 已开始竞拍重复 start → 拒绝
    repeat_start = AuctionClient(merchant).admin_start(aid)
    assert_failed(repeat_start, "重复 start")

    # 2. 取消竞拍
    require_ok(AuctionClient(merchant).admin_cancel(aid, "test"), "取消竞拍")

    # 3. 已取消竞拍重复 cancel → 拒绝
    repeat_cancel = AuctionClient(merchant).admin_cancel(aid, "test")
    assert_failed(repeat_cancel, "重复 cancel")
