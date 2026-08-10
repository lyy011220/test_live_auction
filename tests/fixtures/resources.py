"""本轮测试创建的活动资源追踪与尽力清理。"""
import pytest

from clients.auction_client import AuctionClient
from clients.base import ApiClient
from clients.room_client import RoomClient
from commons.logger_util import info_log


def _cleanup_auction(client: ApiClient, auction_id) -> None:
    try:
        AuctionClient(client).admin_cancel(auction_id, "qa fixture cleanup", name="清理竞拍")
    except Exception as exc:  # noqa: BLE001
        info_log(f"清理竞拍 {auction_id} 跳过: {exc}")


def _cleanup_room(client: ApiClient, room_id) -> None:
    try:
        RoomClient(client).stop(room_id, name="清理直播间")
    except Exception as exc:  # noqa: BLE001
        info_log(f"清理直播间 {room_id} 跳过: {exc}")


@pytest.fixture(autouse=True)
def resource_cleanup(monkeypatch):
    """记录本例成功创建的资源，结束时先取消竞拍、再停止直播间。"""
    auctions: list[tuple[ApiClient, object]] = []
    rooms: list[tuple[ApiClient, object]] = []
    original_auction_create = AuctionClient.admin_create
    original_room_create = RoomClient.create

    def tracked_auction_create(client, *args, **kwargs):
        response = original_auction_create(client, *args, **kwargs)
        if response.is_ok and isinstance(response.data, dict) and response.data.get("id") is not None:
            auctions.append((client.c, response.data["id"]))
        return response

    def tracked_room_create(client, *args, **kwargs):
        response = original_room_create(client, *args, **kwargs)
        if response.is_ok and isinstance(response.data, dict) and response.data.get("id") is not None:
            rooms.append((client.c, response.data["id"]))
        return response

    monkeypatch.setattr(AuctionClient, "admin_create", tracked_auction_create)
    monkeypatch.setattr(RoomClient, "create", tracked_room_create)
    yield

    seen_auctions = set()
    for client, auction_id in reversed(auctions):
        key = (id(client), auction_id)
        if key not in seen_auctions:
            seen_auctions.add(key)
            _cleanup_auction(client, auction_id)

    seen_rooms = set()
    for client, room_id in reversed(rooms):
        key = (id(client), room_id)
        if key not in seen_rooms:
            seen_rooms.add(key)
            _cleanup_room(client, room_id)
