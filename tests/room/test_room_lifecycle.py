"""ROOM 域 | 房间生命周期、数据和列表查询。"""
import allure
import pytest

from clients.auction_client import AuctionClient
from clients.room_client import RoomClient
from models.enums import RoomStatus
from support.assertions import assert_failed, assert_fields, assert_ok, require_ok
from support.traceability import case

EPIC = allure.epic("直播竞拍平台")
FEATURE = allure.feature("直播间域")

MISSING_ROOM_ID = 99999999  # 约定不存在的房间 id

@EPIC
@FEATURE
@allure.story("ROOM-NOR-001")
@allure.severity(allure.severity_level.CRITICAL)
@allure.title("ROOM-NOR-001 主播创建直播间并返回唯一标识")
@pytest.mark.room
@pytest.mark.api
@case("ROOM-NOR-001")
def test_room_nor_001_create_room(merchant_client, unique_name):
    """核心预期: 主播创建未开播房间, 返回唯一房间 id。"""
    resp = RoomClient(merchant_client).create(title=unique_name("room"))
    assert_ok(resp, "创建直播间")
    data = resp.data or {}
    assert data.get("id"), "应返回房间 id"
    # 新建房间应为未开播状态
    assert data.get("status") in (None, RoomStatus.CREATED), (
        f"新建房间应为未开播(1), 实际 status={data.get('status')}"
    )

@EPIC
@FEATURE
@allure.story("ROOM-NOR-002")
@allure.severity(allure.severity_level.NORMAL)
@allure.title("ROOM-NOR-002 主播修改自己的房间信息")
@pytest.mark.room
@pytest.mark.api
@case("ROOM-NOR-002")
def test_room_nor_002_update_room(merchant_client, unique_name):
    """核心预期: 主播可更新房间 title/notice 且修改结果持久化。"""
    room = RoomClient(merchant_client)
    # 1. 创建并开播
    created = require_ok(room.create(title="test room"), "创建直播间")
    room_id = created.data["id"]
    assert_ok(room.start(room_id), "开播")

    # 2. 修改 title + notice (PUT /api/admin/room/{id})
    new_title = "updated"
    new_notice = "修改后的公告"
    resp = room.update(room_id, title=new_title, notice=new_notice)
    assert_ok(resp, "修改房间信息")

    my = require_ok(room.get_my_room(), "查询我的直播间")
    assert_fields(my, {"title": new_title, "notice": new_notice}, "修改后房间信息")

@EPIC
@FEATURE
@allure.story("ROOM-STA-001")
@allure.severity(allure.severity_level.CRITICAL)
@allure.title("ROOM-STA-001 主播开播房间进入直播状态并可查询")
@pytest.mark.room
@pytest.mark.api
@case("ROOM-STA-001")
def test_room_sta_001_start_room(merchant_client, unique_name):
    """核心预期: 开播后房间进入直播状态(LIVE=2)且可被正确查询。"""
    room = RoomClient(merchant_client)
    created = require_ok(room.create(title=unique_name("room")), "创建直播间")
    rid = created.data["id"]

    assert_ok(room.start(rid), "开播")

    my = require_ok(room.get_my_room(), "查询我的直播间")
    assert_fields(my, {"id": rid, "status": RoomStatus.LIVE}, "开播后我的直播间")

@EPIC
@FEATURE
@allure.story("ROOM-STA-002")
@allure.severity(allure.severity_level.NORMAL)
@allure.title("ROOM-STA-002 主播下播房间停止直播并更新列表")
@pytest.mark.room
@pytest.mark.api
@case("ROOM-STA-002")
def test_room_sta_002_stop_room(merchant_client, anonymous_client, unique_name):
    """核心预期: 下播后房间状态变为 ENDED(3) 且不在公开直播列表中。"""
    room = RoomClient(merchant_client)
    created = require_ok(room.create(title=unique_name("room")), "创建直播间")
    rid = created.data["id"]
    require_ok(room.start(rid), "开播")
    require_ok(room.stop(rid), "下播")

    # 1. 状态变为 ENDED
    my = require_ok(room.get_my_room(), "查询我的直播间")
    assert my.data.get("status") == RoomStatus.ENDED, (
        f"下播后状态应为 ENDED(3), 实际 {my.data.get('status')}"
    )

    # 2. 不在公开直播列表中
    pub = require_ok(RoomClient(anonymous_client).public_list(), "查询直播列表")
    ids = [r.get("id") for r in (pub.data or [])]
    assert rid not in ids, f"下播房间 {rid} 不应出现在直播列表中"

@EPIC
@FEATURE
@allure.story("ROOM-DAT-001")
@allure.severity(allure.severity_level.NORMAL)
@allure.title("ROOM-DAT-001 主播查询自己的直播间")
@pytest.mark.room
@pytest.mark.api
@case("ROOM-DAT-001")
def test_room_dat_001_query_my_room(merchant_client, unique_name):
    """核心预期: 返回当前主播所属房间及正确标识。"""
    room = RoomClient(merchant_client)
    title = unique_name("room")
    created = require_ok(room.create(title=title), "创建直播间")
    rid = created.data["id"]

    my = require_ok(room.get_my_room(), "查询我的直播间")
    assert_fields(my, {"id": rid, "title": title, "status": RoomStatus.CREATED}, "我的直播间")

@EPIC
@FEATURE
@allure.story("ROOM-LST-001")
@allure.severity(allure.severity_level.NORMAL)
@allure.title("ROOM-LST-001 用户查询房间列表")
@pytest.mark.room
@pytest.mark.api
@case("ROOM-LST-001")
def test_room_lst_001_public_list(merchant_client, anonymous_client, unique_name):
    """核心预期: 用户查询直播中房间列表, 返回房间及在线信息。"""
    room = RoomClient(merchant_client)
    created = require_ok(room.create(title=unique_name("room")), "创建直播间")
    rid = created.data["id"]
    require_ok(room.start(rid), "开播")

    pub = require_ok(RoomClient(anonymous_client).public_list(), "查询直播列表")
    rooms = pub.data or []
    matched = [r for r in rooms if r.get("id") == rid]
    assert matched, f"直播列表应包含刚开播的房间: rid = {rid}"
    r = matched[0]
    assert r.get("status") == RoomStatus.LIVE, "列表中房间应为直播中"
    assert "online" in r, "房间信息应包含在线人数"

@EPIC
@FEATURE
@allure.story("ROOM-DAT-002")
@allure.severity(allure.severity_level.NORMAL)
@allure.title("ROOM-DAT-002 查询房间在线人数")
@pytest.mark.room
@pytest.mark.api
@case("ROOM-DAT-002")
def test_room_dat_002_online_count(merchant_client, unique_name):
    """核心预期: 房间标识与实时在线人数准确。"""
    room = RoomClient(merchant_client)
    created = require_ok(room.create(title=unique_name("room")), "创建直播间")
    rid = created.data["id"]
    require_ok(room.start(rid), "开播")

    oc = require_ok(room.online_count(rid), "查询在线人数")
    data = oc.data or {}
    assert data.get("roomId") == rid, f"应返回正确的 roomId, 实际 {data.get('roomId')}"
    assert "online" in data, "应返回在线人数字段"

@EPIC
@FEATURE
@allure.story("ROOM-LST-002")
@allure.severity(allure.severity_level.NORMAL)
@allure.title("ROOM-LST-002 主播直播中房间列表包含本轮房间")
@pytest.mark.room
@pytest.mark.api
@case("ROOM-LST-002")
def test_room_lst_002_admin_live_rooms_contains_current(live_room):
    ctx = live_room
    resp = require_ok(RoomClient(ctx["merchantClient"]).get_live_rooms(), "查询后台直播中房间")
    assert isinstance(resp.data, list), f"直播中房间 data 应为 list，实际 {type(resp.data).__name__}"
    matched = [room for room in resp.data if room.get("id") == ctx["roomId"]]
    assert matched, f"后台直播中房间列表应包含本轮房间 {ctx['roomId']}"
    assert matched[0].get("status") == RoomStatus.LIVE, "后台列表中的房间应为直播中"

@EPIC
@FEATURE
@allure.story("ROOM-STA-003")
@allure.severity(allure.severity_level.NORMAL)
@allure.title("ROOM-STA-003 重复开播、下播及下播后重开")
@pytest.mark.room
@pytest.mark.api
@case("ROOM-STA-003")
def test_room_sta_003_repeat_state_change(merchant_client, unique_name):
    """核心预期: 重复 start/stop 被拒绝, 下播后可重新开播。"""
    room = RoomClient(merchant_client)
    created = require_ok(room.create(title=unique_name("room")), "创建直播间")
    rid = created.data["id"]

    # 1. 开播后重复开播 → 拒绝
    require_ok(room.start(rid), "首次开播")
    repeat_start = room.start(rid)
    assert_failed(repeat_start, "重复开播")

    # 2. 下播后重复下播 → 拒绝
    require_ok(room.stop(rid), "下播")
    repeat_stop = room.stop(rid)
    assert_failed(repeat_stop, "重复下播")

    # 3. 下播后重新开播 → 成功
    reopen = room.start(rid)
    assert_ok(reopen, "下播后重新开播")
    my = require_ok(room.get_my_room(), "查询状态")
    assert my.data.get("status") == RoomStatus.LIVE, (
        f"重开后应为 LIVE(2), 实际 {my.data.get('status')}"
    )

@EPIC
@FEATURE
@allure.story("ROOM-STA-004")
@allure.severity(allure.severity_level.NORMAL)
@allure.title("ROOM-STA-004 下播后房间内竞拍状态")
@pytest.mark.room
@pytest.mark.api
@case("ROOM-STA-004")
def test_room_sta_004_auction_after_stop(started_auction):
    """核心预期: 房间有进行中竞拍时下播, 房间结束且竞拍数据不被误改。"""
    ctx = started_auction
    merchant = ctx["merchantClient"]
    rid = ctx["roomId"]
    aid = ctx["auctionId"]

    room = RoomClient(merchant)
    before = require_ok(AuctionClient(merchant).public_detail(aid), "下播前竞拍详情")
    before_data = before.data or {}
    require_ok(room.stop(rid), "下播(有进行中竞拍)")

    my_room = require_ok(room.get_my_room(), "查询下播后房间")
    assert_fields(my_room, {"id": rid, "status": RoomStatus.ENDED}, "下播后房间")

    after = require_ok(AuctionClient(merchant).public_detail(aid), "下播后竞拍详情")
    after_data = after.data or {}
    assert after_data.get("currentPrice") == before_data.get("currentPrice"), "下播不得修改竞拍价格"
    assert after_data.get("bidCount") == before_data.get("bidCount"), "下播不得增加竞拍次数"