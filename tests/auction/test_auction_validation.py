"""AUC 域 | 参数、资源和归属权限校验。"""
import allure
import pytest

from clients.auction_client import AuctionClient
from clients.room_client import RoomClient
from models.payloads import AuctionPayload, default_auction_payload
from support.assertions import assert_failed, require_ok
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
@allure.story("AUC-VAL-001")
@allure.severity(allure.severity_level.NORMAL)
@allure.title("AUC-VAL-001 创建竞拍的 roomId 缺失或不存在")
@pytest.mark.auction
@pytest.mark.api
@case("AUC-VAL-001")
@pytest.mark.parametrize("room_id", [MISSING_ROOM_ID, None], ids=["roomId不存在", "roomId缺失"])
def test_auc_val_001_invalid_room_id(merchant_client, room_id):
    """核心预期: 不创建无有效目标房间的竞拍。"""
    payload = default_auction_payload()
    if room_id is not None:
        payload["roomId"] = room_id
    resp = AuctionClient(merchant_client).admin_create(payload)
    assert_failed(resp, "无效 roomId 建竞拍")

@EPIC
@FEATURE
@allure.story("AUC-RES-001")
@allure.severity(allure.severity_level.NORMAL)
@allure.title("AUC-RES-001 读取或管理不存在的竞拍")
@pytest.mark.auction
@pytest.mark.api
@case("AUC-RES-001")
def test_auc_res_001_missing_auction(merchant_client):
    """核心预期: 不存在 auctionId detail/start/cancel 被拒绝且无副作用。"""
    ac = AuctionClient(merchant_client)
    detail = ac.admin_detail(MISSING_AUCTION_ID)
    assert_failed(detail, "查看不存在竞拍")
    start = ac.admin_start(MISSING_AUCTION_ID)
    assert_failed(start, "开始不存在竞拍")
    cancel = ac.admin_cancel(MISSING_AUCTION_ID, "test")
    assert_failed(cancel, "取消不存在竞拍")

@EPIC
@FEATURE
@allure.story("AUC-AUT-001")
@allure.severity(allure.severity_level.CRITICAL)
@allure.title("AUC-AUT-001 创建竞拍的角色与房间归属不一致被拒绝")
@pytest.mark.auction
@pytest.mark.api
@case("AUC-AUT-001")
def test_auc_aut_001_cross_owner_create(make_merchant, unique_name):
    """核心预期: 主播B 用主播A 的 roomId 建竞拍, 鉴权失败且不落库。"""
    # 主播 A 建房并开播
    merchant_a = make_merchant()
    room_a = RoomClient(merchant_a)
    created = require_ok(room_a.create(title=unique_name("room")), "主播A创建房间")
    rid = created.data["id"]
    require_ok(room_a.start(rid), "主播A开播")
    before_ids = _room_auction_ids(merchant_a, rid)

    # 主播 B 用 A 的 roomId 建竞拍
    merchant_b = make_merchant()
    resp = AuctionClient(merchant_b).admin_create(
        AuctionPayload().for_room(rid).to_dict()
    )
    assert_failed(resp, "跨归属建竞拍")
    assert _room_auction_ids(merchant_a, rid) == before_ids, "跨归属创建不得新增竞拍"

@EPIC
@FEATURE
@allure.story("AUC-VAL-002")
@allure.severity(allure.severity_level.NORMAL)
@allure.title("AUC-VAL-002 竞拍字段超出数值边界")
@pytest.mark.auction
@pytest.mark.api
@case("AUC-VAL-002")
@pytest.mark.parametrize(
    "overrides, desc",
    [
        ({"startPrice": 0}, "起拍价<0"),
        ({"startPrice": 500, "maxPrice": 100}, "最高价<起拍价"),
        ({"incrementAmount": 0}, "加价幅度<=0"),
    ],
    ids=["起拍价<=0", "最高价<起拍价", "加价幅度<=0"],
)
def test_auc_val_002_numeric_boundary(live_room, overrides, desc):
    """核心预期: 非法数值边界建竞拍被拒绝且不落库。"""
    merchant = live_room["merchantClient"]
    rid = live_room["roomId"]
    before_ids = _room_auction_ids(merchant, rid)
    payload = AuctionPayload().for_room(rid).with_(**overrides).to_dict()
    resp = AuctionClient(merchant).admin_create(payload)
    assert_failed(resp, desc)
    assert _room_auction_ids(merchant, rid) == before_ids, f"{desc} 不得新增竞拍"

@EPIC
@FEATURE
@allure.story("AUC-AUT-002")
@allure.severity(allure.severity_level.CRITICAL)
@allure.title("AUC-AUT-002 跨主播更新竞拍被拒绝")
@pytest.mark.auction
@pytest.mark.api
@case("AUC-AUT-002")
def test_auc_aut_002_cross_owner_update(pending_auction, make_merchant):
    """核心预期: 主播B 更新主播A 的竞拍, 鉴权失败且不得误改 incrementAmount。

    独立用例: 与 cancel 分离, 任一被后端错误放行不影响另一个的判定。
    先验终态(攻击前后快照一致)再验拒绝。
    """
    merchant_a = pending_auction["merchantClient"]
    aid = pending_auction["auctionId"]
    merchant_b = make_merchant()

    # 攻击前快照 (未开拍态, 仅 update 可改)
    detail_before = require_ok(AuctionClient(merchant_a).admin_detail(aid), "攻击前详情")
    inc_before = detail_before.data.get("incrementAmount")

    # 主播 B 跨归属 update
    resp = AuctionClient(merchant_b).admin_update(aid, {"incrementAmount": 99})

    # 先验终态 (incrementAmount 不变) 再验拒绝
    detail_after = require_ok(AuctionClient(merchant_a).admin_detail(aid), "攻击后详情")
    inc_after = detail_after.data.get("incrementAmount")
    assert inc_after == inc_before, (
        f"跨归属 update 不得误改 incrementAmount: {inc_before} -> {inc_after}"
    )
    assert_failed(resp, "跨归属 update")

@EPIC
@FEATURE
@allure.story("AUC-AUT-003")
@allure.severity(allure.severity_level.CRITICAL)
@allure.title("AUC-AUT-003 跨主播取消竞拍被拒绝")
@pytest.mark.auction
@pytest.mark.api
@case("AUC-AUT-003")
def test_auc_aut_003_cross_owner_cancel(started_auction, make_merchant):
    """核心预期: 主播B 取消主播A 的竞拍, 鉴权失败且不得误改 status。

    独立用例: 与 update 分离, 任一被后端错误放行不影响另一个的判定。
    先验终态(攻击前后快照一致)再验拒绝。
    """
    merchant_a = started_auction["merchantClient"]
    aid = started_auction["auctionId"]
    merchant_b = make_merchant()

    # 攻击前快照 (已开拍, status=LIVE)
    detail_before = require_ok(AuctionClient(merchant_a).admin_detail(aid), "攻击前详情")
    status_before = detail_before.data.get("status")

    # 主播 B 跨归属 cancel
    resp = AuctionClient(merchant_b).admin_cancel(aid, "hack")

    # 先验终态 (status 不变) 再验拒绝
    detail_after = require_ok(AuctionClient(merchant_a).admin_detail(aid), "攻击后详情")
    status_after = detail_after.data.get("status")
    assert status_after == status_before, (
        f"跨归属 cancel 不得误改 status: {status_before} -> {status_after}"
    )
    assert_failed(resp, "跨归属 cancel")
