"""ROOM 域 | 参数、资源、归属和状态限制。"""
import allure
import pytest

from clients.room_client import RoomClient
from support.assertions import assert_failed, require_ok
from support.traceability import case

EPIC = allure.epic("直播竞拍平台")
FEATURE = allure.feature("直播间域")

MISSING_ROOM_ID = 99999999  # 约定不存在的房间 id

@EPIC
@FEATURE
@allure.story("ROOM-RES-001")
@allure.severity(allure.severity_level.NORMAL)
@allure.title("ROOM-RES-001 管理不存在的房间")
@pytest.mark.room
@pytest.mark.api
@case("ROOM-RES-001")
def test_room_res_001_manage_missing_room(merchant_client):
    """核心预期: 对不存在 roomId 的操作被拒绝且不伪造资源。"""
    room = RoomClient(merchant_client)
    start_resp = room.start(MISSING_ROOM_ID)
    assert_failed(start_resp, "启动不存在房间")
    stop_resp = room.stop(MISSING_ROOM_ID)
    assert_failed(stop_resp, "停止不存在房间")

@EPIC
@FEATURE
@allure.story("ROOM-AUT-001")
@allure.severity(allure.severity_level.CRITICAL)
@allure.title("ROOM-AUT-001 普通用户进行房间管理被鉴权拒绝")
@pytest.mark.room
@pytest.mark.api
@case("ROOM-AUT-001")
def test_room_aut_001_user_manage_room(bidder_client, unique_name):
    """核心预期: 普通用户调 /api/admin/room 应被鉴权拒绝。"""
    resp = RoomClient(bidder_client).create(title=unique_name("room"))
    assert_failed(resp, "普通用户创建房间")

@EPIC
@FEATURE
@allure.story("ROOM-AUT-002")
@allure.severity(allure.severity_level.CRITICAL)
@allure.title("ROOM-AUT-002 主播跨归属管理房间被拒绝")
@pytest.mark.room
@pytest.mark.api
@case("ROOM-AUT-002")
def test_room_aut_002_cross_owner_manage(make_merchant, unique_name):
    """核心预期: 主播A 用主播B 的 roomId 操作, 鉴权失败且不得误改他人房间。"""
    # 主播 A 建房并开播
    merchant_a = make_merchant()
    room_a = RoomClient(merchant_a)
    created = require_ok(room_a.create(title=unique_name("roomA")), "主播A创建直播间")
    rid = created.data["id"]
    require_ok(room_a.start(rid), "主播A开播")

    # 主播 B 尝试操作 A 的房间
    merchant_b = make_merchant()
    room_b = RoomClient(merchant_b)
    stop_resp = room_b.stop(rid)
    assert_failed(stop_resp, "跨归属停止房间")
    update_resp = room_b.update(rid, title="hacked")
    assert_failed(update_resp, "跨归属修改房间")

    # A 的房间未被误改
    my = require_ok(room_a.get_my_room(), "查询主播A的直播间")
    assert my.data.get("title") != "hacked", "不得误改他人房间标题"

@EPIC
@FEATURE
@allure.story("ROOM-VAL-001")
@allure.severity(allure.severity_level.NORMAL)
@allure.title("ROOM-VAL-001 房间标题缺失、空值及空白")
@pytest.mark.room
@pytest.mark.api
@case("ROOM-VAL-001")
@pytest.mark.parametrize("title", ["", "   "], ids=["房间标题为空字符串", "房间标题为纯空白"])
def test_room_val_001_invalid_title(merchant_client, title):
    """核心预期: 非法标题建房被拒绝且不落库。"""
    room = RoomClient(merchant_client)
    resp = room.create(title=title)
    assert_failed(resp, "非法标题创建房间")
    # 非法输入不应落库: get_my_room 应无房间或失败
    my = room.get_my_room()
    assert not my.is_ok or not my.data, "非法标题不应创建房间"

@EPIC
@FEATURE
@allure.story("ROOM-RES-002")
@allure.severity(allure.severity_level.NORMAL)
@allure.title("ROOM-RES-002 不存在房间的在线人数查询")
@pytest.mark.room
@pytest.mark.api
@case("ROOM-RES-002")
def test_room_res_002_online_count_missing(merchant_client):
    """核心预期: 不存在 roomId 查询在线人数应被拒绝且不返回其他房间数据。"""
    resp = RoomClient(merchant_client).online_count(MISSING_ROOM_ID)
    assert_failed(resp, "查询不存在房间的在线人数")
