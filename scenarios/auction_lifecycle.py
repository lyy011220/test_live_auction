"""竞拍生命周期编排: 注册主播 -> 建直播间 -> 开播 -> 发布竞拍 -> 开始竞拍。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from clients.auction_client import AuctionClient
from clients.auth_client import default_password, get_token, register_merchant, unique_username
from clients.base import ApiClient
from clients.room_client import RoomClient
from models.payloads import default_auction_payload
from support.assertions import require_ok


@dataclass(frozen=True)
class AuctionContext:
    """生命周期上下文；对测试统一导出既有 camelCase fixture 字典。"""

    merchant_client: ApiClient
    merchant_token: str
    merchant_id: Any
    room_id: Any
    auction_id: Any | None = None

    def to_fixture_dict(self) -> dict[str, Any]:
        result = {
            "merchantClient": self.merchant_client,
            "merchantToken": self.merchant_token,
            "merchantId": self.merchant_id,
            "roomId": self.room_id,
        }
        if self.auction_id is not None:
            result["auctionId"] = self.auction_id
        return result


class AuctionLifecycle:
    """链式 builder, 复用 clients, 不在测试里拼 URL。"""

    def __init__(self, *, password: str | None = None):
        self.password = password or default_password()
        self._merchant: ApiClient | None = None
        self._room = None
        self._auction = None
        self._auction_id: Any | None = None

    def create_merchant(self, username: str | None = None) -> "AuctionLifecycle":
        self._merchant = register_merchant(username=username, password=self.password)
        return self

    def create_room(self, title: str | None = None) -> "AuctionLifecycle":
        assert self._merchant is not None, "需先 create_merchant"
        title = title or unique_username("qa_room")
        self._room = require_ok(RoomClient(self._merchant).create(title=title), "create room")
        return self

    def start_room(self) -> "AuctionLifecycle":
        assert self._room is not None, "需先 create_room"
        rid = self._room.data["id"]
        require_ok(RoomClient(self._merchant).start(rid), "start room")
        return self

    def create_auction(self, payload: Mapping[str, Any] | None = None) -> "AuctionLifecycle":
        assert self._room is not None, "需先 create_room/start_room"
        rid = self._room.data["id"]
        p = default_auction_payload()
        p.update(dict(payload or {}))
        p["roomId"] = rid
        self._auction = require_ok(AuctionClient(self._merchant).admin_create(p), "create auction")
        return self

    def start_auction(self) -> "AuctionLifecycle":
        assert self._auction is not None, "需先 create_auction"
        self._auction_id = self._auction.data["id"]
        require_ok(AuctionClient(self._merchant).admin_start(self._auction_id), "start auction")
        return self

    def context(self, auction_id: Any | None = None) -> AuctionContext:
        """构造当前生命周期上下文，避免各阶段重复映射字段。"""
        assert self._merchant is not None, "需先 create_merchant"
        assert self._room is not None, "需先 create_room"
        return AuctionContext(
            merchant_client=self._merchant,
            merchant_token=get_token(self._merchant),
            merchant_id=self._merchant.user_id,
            room_id=self._room.data["id"],
            auction_id=auction_id,
        )

    def started(self) -> AuctionContext:
        assert self._auction_id is not None, "需先 start_auction"
        return self.context(self._auction_id)

    def pending(self) -> AuctionContext:
        assert self._auction is not None, "需先 create_auction"
        return self.context(self._auction.data["id"])

    def create_live_room(self, title: str = "test_room") -> dict[str, Any]:
        """便捷: 一步到已开播房间 (未建竞拍), 供 ROOM/AUC 域复用。"""
        self.create_merchant().create_room(title=title).start_room()
        return self.context().to_fixture_dict()

    def create_started_auction(self, **payload) -> dict[str, Any]:
        """便捷: 一步到已开始竞拍, 返回上下文字典。"""
        self.create_merchant().create_room().start_room().create_auction(payload or None).start_auction()
        return self.started().to_fixture_dict()

    def create_pending_auction(self, **payload) -> dict[str, Any]:
        """便捷: 一步到待开始竞拍 (未 start), 供状态机用例。"""
        self.create_merchant().create_room().start_room().create_auction(payload or None)
        return self.pending().to_fixture_dict()
