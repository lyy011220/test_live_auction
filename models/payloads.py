"""竞拍请求体构建器。"""
from __future__ import annotations

from copy import deepcopy
from typing import Any


DEFAULT_AUCTION_PAYLOAD: dict[str, Any] = {
    "name": "qa_live_auction_item",
    "description": "created by live_auction_qa",
    "images": "https://example.com/item.png",
    "startPrice": 100,
    "incrementAmount": 9,
    "maxPrice": 1000,
    "durationMinutes": 5,
    "delaySeconds": 10,
}


def default_auction_payload() -> dict[str, Any]:
    return deepcopy(DEFAULT_AUCTION_PAYLOAD)


class AuctionPayload:
    """竞拍 payload 构建器, 支持 .with_(**overrides) 链式覆盖。"""

    def __init__(self, **overrides: Any):
        self.data = default_auction_payload()
        self.data.update(overrides)

    def with_(self, **overrides: Any) -> "AuctionPayload":
        self.data.update(overrides)
        return self

    def for_room(self, room_id: Any) -> "AuctionPayload":
        self.data["roomId"] = room_id
        return self

    def to_dict(self) -> dict[str, Any]:
        return deepcopy(self.data)
